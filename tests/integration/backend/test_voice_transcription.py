"""Isolated PostgreSQL, real audio extraction, mocked Voice responses; no inference."""

import array
import json
import subprocess
import wave
from datetime import timedelta
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr
from sqlalchemy import func, select, update

from intentcut.ai.voice import inspect_wav, parse_transcript
from intentcut.backend.ai_artifacts import AIArtifactPublisher
from intentcut.backend.ai_job_service import AIJobAPIError, AIJobService
from intentcut.backend.ai_worker import AIJobWorker
from intentcut.backend.app import create_app
from intentcut.backend.contracts import (
    AIProcessingError,
    JobLeaseLost,
    ProcessingResult,
)
from intentcut.backend.shared.persistence_errors import CommitOutcomeUnknown
from intentcut.backend.storage.database_models import AIJob
from intentcut.backend.transcription.media import extract_audio, verified_video
from intentcut.backend.transcription.processor import TranscriptionProcessor
from intentcut.backend.transcription.repository import (
    PIPELINE,
    cache_caption,
    reserve_provider_call,
)

pytestmark = [pytest.mark.integration, pytest.mark.postgres]


@pytest.fixture(scope="session")
def audio_videos(tmp_path_factory):
    root = tmp_path_factory.mktemp("voice-video-fixtures")
    result = {}
    for kind in ("tone", "silent"):
        path = root / f"{kind}.mp4"
        audio = (
            "sine=frequency=440:sample_rate=48000:duration=1"
            if kind == "tone"
            else "anullsrc=r=48000:cl=stereo:d=1"
        )
        subprocess.run(
            [
                "ffmpeg",
                "-v",
                "error",
                "-nostdin",
                "-f",
                "lavfi",
                "-i",
                "color=blue:s=160x90:r=24:d=2",
                "-itsoffset",
                "0.5",
                "-f",
                "lavfi",
                "-i",
                audio,
                "-map",
                "0:v",
                "-map",
                "1:a",
                "-c:v",
                "libx264",
                "-preset",
                "ultrafast",
                "-threads",
                "1",
                "-pix_fmt",
                "yuv420p",
                "-c:a",
                "aac",
                "-t",
                "2",
                str(path),
            ],
            check=True,
            capture_output=True,
            timeout=30,
        )
        result[kind] = path.read_bytes()
    return result


@pytest.fixture
def voice_settings(settings):
    return settings.model_copy(
        update={
            "voice_transcription_enabled": True,
            "ai_jobs_local_enabled": True,
            "model_api_key": SecretStr("fake-voice-key"),
        }
    )


@pytest.fixture
def api(voice_settings, database, storage):
    app = create_app(voice_settings, database=database, storage=storage)
    with TestClient(
        app, base_url="http://127.0.0.1:8000", client=("127.0.0.1", 12345)
    ) as client:
        yield client


def publish_source(database, storage, tmp_path, data):
    project = database.create_project("Voice fixture")
    job = database.create_ai_job(project.id, {"pipeline_version": "uploaded_v1"})
    claimed = database.claim_next_ai_job(job_id=job.id)
    video = tmp_path / f"{job.id}.mp4"
    video.write_bytes(data)
    board = tmp_path / f"{job.id}.json"
    board.write_text("{}")
    publisher = AIArtifactPublisher(storage)
    assert publisher.publish_and_complete(
        database,
        project.id,
        job.id,
        claimed.lease_token,
        ProcessingResult(board, video),
    )
    artifact = next(
        a
        for a in database.list_ai_job_artifacts(project.id, job.id)
        if a.kind == "video"
    )
    return project.id, artifact


@pytest.fixture
def source(database, storage, tmp_path, audio_videos):
    return publish_source(database, storage, tmp_path, audio_videos["tone"])


def submit(api, source, request_id=None):
    project, artifact = source
    return api.post(
        f"/projects/{project}/ai-jobs/transcriptions",
        json={
            "request_id": str(request_id or uuid4()),
            "artifact_id": str(artifact.id),
        },
    )


class FakeVoice:
    def __init__(self, *, fail=None, empty=False, on_call=None):
        self.calls = []
        self.fail, self.empty, self.on_call = fail, empty, on_call

    def transcribe(self, path, session, duration_ms):
        assert inspect_wav(path) == (duration_ms, False)
        self.calls.append((session, duration_ms))
        if self.on_call:
            self.on_call()
        if self.fail:
            raise AIProcessingError(self.fail)
        data = {
            "sessionId": str(session),
            "audioDurationMs": duration_ms,
            "transcript": "" if self.empty else "Fixture speech.",
            "turns": []
            if self.empty
            else [
                {
                    "turnId": 1,
                    "startMs": 500,
                    "endMs": 1200,
                    "transcript": "Fixture speech.",
                }
            ],
        }
        return parse_transcript(json.dumps(data).encode(), duration_ms)


def worker(database, storage, settings, voice, publisher=None):
    return AIJobWorker(
        database,
        TranscriptionProcessor(AIJobService(database, storage, settings), voice),
        artifact_publisher=publisher or AIArtifactPublisher(storage),
    )


def test_full_admission_extraction_publication_and_retrieval(
    api, source, database, storage, voice_settings
):
    request_id = uuid4()
    accepted = submit(api, source, request_id)
    assert accepted.status_code == 202, accepted.text
    urls = accepted.json()
    assert urls["status"] == "queued"
    assert api.get(urls["status_url"]).json()["progress"] is None
    claimed_payload = database.get_ai_job(source[0], request_id).request_payload
    assert claimed_payload == {
        "pipeline_version": PIPELINE,
        "parent_artifact_id": str(source[1].id),
        "parent_sha256": source[1].sha256,
    }
    stages = []

    def check_transaction_and_progress():
        # A separate connection observes the durable marker and can heartbeat;
        # no transaction remains open across the fake provider inference.
        current = database.get_ai_job(source[0], request_id)
        assert current.request_payload["voice_call_started"] is True
        assert database.heartbeat_ai_job(source[0], request_id, current.lease_token)
        status = api.get(urls["status_url"]).json()
        stages.append(status["progress"]["stage"])
        assert status["status"] == "running"

    voice = FakeVoice(on_call=check_transaction_and_progress)
    executor = worker(database, storage, voice_settings, voice)
    assert executor.supported_job_types == (PIPELINE,)
    assert executor.process_one(job_id=request_id)
    assert stages == ["transcribing_audio"]
    assert len(voice.calls) == 1
    status = api.get(urls["status_url"]).json()
    assert status["status"] == "succeeded" and status["progress"] is None
    for private in (
        "lease_token",
        "request_payload",
        "voice_caption",
        "voice_call_started",
    ):
        assert private not in status
    items = api.get(urls["artifacts_url"]).json()["items"]
    assert len(items) == 1 and items[0]["kind"] == "captions"
    assert items[0]["parent_artifact_id"] == str(source[1].id)
    assert items[0]["parent_sha256"] == source[1].sha256
    download = api.get(items[0]["download_url"])
    assert download.status_code == 200
    assert download.headers["content-type"] == "application/json"
    document = download.json()
    assert document["duration_ms"] == 2000
    assert document["cues"] == [
        {"start_ms": 500, "end_ms": 1200, "text": "Fixture speech."}
    ]
    repeated = submit(api, source, request_id)
    assert (
        repeated.json()["id"] == str(request_id)
        and repeated.json()["status"] == "succeeded"
    )
    assert submit(api, source).json()["id"] == str(request_id)
    assert not executor.process_one(job_id=request_id)
    assert len(voice.calls) == 1


def test_full_wav_timeline_preserves_delayed_audio_and_tail(
    database, storage, voice_settings, source, tmp_path
):
    jobs = AIJobService(database, storage, voice_settings)
    with verified_video(jobs, source[0], source[1].id, 120) as (_, metadata, video):
        assert metadata.audio.start_time > 0.4
        wav = tmp_path / "extracted.wav"
        assert extract_audio(video, metadata, wav) == (2000, False)
    with wave.open(str(wav), "rb") as stream:
        assert (
            stream.getnchannels(),
            stream.getsampwidth(),
            stream.getframerate(),
        ) == (1, 2, 24000)
        samples = array.array("h", stream.readframes(stream.getnframes()))
    assert len(samples) == 48000
    assert max(abs(s) for s in samples[:8400]) == 0  # First 350 ms stays silent.
    assert max(abs(s) for s in samples[15600:24000]) > 1000
    assert max(abs(s) for s in samples[42000:]) == 0  # Last 250 ms is preserved.


@pytest.mark.parametrize("kind", ["silent", "no_audio", "provider_empty"])
def test_empty_audio_or_transcript_is_truthful(
    api,
    database,
    storage,
    voice_settings,
    tmp_path,
    audio_videos,
    artifact_video_bytes,
    kind,
):
    data = (
        artifact_video_bytes
        if kind == "no_audio"
        else audio_videos["silent" if kind == "silent" else "tone"]
    )
    source = publish_source(database, storage, tmp_path, data)
    response = submit(api, source)
    job_id = response.json()["id"]
    voice = FakeVoice(empty=True)
    assert worker(database, storage, voice_settings, voice).process_one(
        job_id=UUID(job_id)
    )
    result = api.get(response.json()["artifacts_url"]).json()["items"][0]
    doc = api.get(result["download_url"]).json()
    assert doc["cues"] == []
    assert len(voice.calls) == (1 if kind == "provider_empty" else 0)


def test_wrong_project_and_non_video_rejected(api, database, source):
    other = database.create_project("Other")
    assert submit(api, (other.id, source[1])).status_code == 404
    storyboard = next(
        a
        for a in database.list_ai_job_artifacts(source[0], source[1].job_id)
        if a.kind == "storyboard"
    )
    assert submit(api, (source[0], storyboard)).status_code == 404
    assert (
        submit(api, (source[0], type("Missing", (), {"id": uuid4()})())).status_code
        == 404
    )


def test_tampered_parent_rejected_before_admission(api, storage, source, database):
    (storage.root / source[1].storage_key).write_bytes(b"tampered")
    response = submit(api, source)
    assert response.status_code == 503
    with database._sessions() as session:
        assert (
            session.scalar(
                select(func.count())
                .select_from(AIJob)
                .where(AIJob.request_payload["pipeline_version"].astext == PIPELINE)
            )
            == 0
        )


@pytest.mark.parametrize(
    "code",
    [
        "transcription_outcome_unknown",
        "provider_unavailable",
        "invalid_transcript",
        "transcription_rate_limited",
    ],
)
def test_safe_provider_failure_and_no_automatic_repayment(
    api, database, storage, voice_settings, source, code
):
    accepted = submit(api, source).json()
    job_id = UUID(accepted["id"])
    voice = FakeVoice(fail=code)
    executor = worker(database, storage, voice_settings, voice)
    assert executor.process_one(job_id=job_id)
    failed = api.get(accepted["status_url"]).json()
    assert failed["status"] == "failed" and failed["error_code"] == code
    assert api.get(accepted["artifacts_url"]).json()["items"] == []
    assert submit(api, source).json()["id"] == str(job_id)
    assert not executor.process_one(job_id=job_id)
    assert len(voice.calls) == 1


def expire(database, job):
    with database.engine.begin() as connection:
        connection.execute(
            update(AIJob)
            .where(AIJob.id == job.id)
            .values(lease_expires_at=func.clock_timestamp() - timedelta(seconds=1))
        )


def test_crash_after_reservation_never_resends_audio(
    api, source, database, storage, voice_settings
):
    accepted = submit(api, source).json()
    old = database.claim_next_ai_job(job_id=UUID(accepted["id"]))
    reserve_provider_call(database, old)
    expire(database, old)
    recovered = database.recover_expired_ai_job(
        job_id=old.id, max_attempts=2, supported_job_types=(PIPELINE,)
    )
    assert recovered.status == "queued" and recovered.progress is None
    voice = FakeVoice()
    assert worker(database, storage, voice_settings, voice).process_one(job_id=old.id)
    failed = api.get(accepted["status_url"]).json()
    assert (
        failed["status"] == "failed"
        and failed["error_code"] == "transcription_outcome_unknown"
    )
    assert voice.calls == []
    with pytest.raises(JobLeaseLost):
        reserve_provider_call(database, old)


def test_recovery_uses_validated_cache_without_second_call(
    api, source, database, storage, voice_settings
):
    accepted = submit(api, source).json()
    old = database.claim_next_ai_job(job_id=UUID(accepted["id"]))
    reserve_provider_call(database, old)
    document = parse_transcript(
        json.dumps(
            {
                "sessionId": "fixture",
                "transcript": "Cached.",
                "audioDurationMs": 2000,
                "turns": [
                    {
                        "turnId": 1,
                        "startMs": 500,
                        "endMs": 1000,
                        "transcript": "Cached.",
                    }
                ],
            }
        ).encode(),
        2000,
    )
    cache_caption(database, old, document)
    expire(database, old)
    database.recover_expired_ai_job(
        job_id=old.id, max_attempts=2, supported_job_types=(PIPELINE,)
    )
    voice = FakeVoice()
    assert worker(database, storage, voice_settings, voice).process_one(job_id=old.id)
    assert voice.calls == []
    assert api.get(accepted["status_url"]).json()["status"] == "succeeded"
    item = api.get(accepted["artifacts_url"]).json()["items"][0]
    assert api.get(item["download_url"]).json()["cues"][0]["text"] == "Cached."
    with pytest.raises(JobLeaseLost):
        cache_caption(database, old, document)


def test_publication_uncertain_commit_reuses_cached_response(
    api, source, database, storage, voice_settings, monkeypatch
):
    accepted = submit(api, source).json()
    job_id = UUID(accepted["id"])
    publisher = AIArtifactPublisher(storage)
    real = database.complete_derived_artifact
    monkeypatch.setattr(
        database,
        "complete_derived_artifact",
        lambda *a: (_ for _ in ()).throw(CommitOutcomeUnknown()),
    )
    voice = FakeVoice()
    assert worker(database, storage, voice_settings, voice, publisher).process_one(
        job_id=job_id
    )
    assert len(voice.calls) == 1
    current = database.get_ai_job(source[0], job_id)
    assert current.status == "running" and "voice_caption" in current.request_payload
    expire(database, current)
    database.recover_expired_ai_job(
        job_id=job_id, max_attempts=2, supported_job_types=(PIPELINE,)
    )
    monkeypatch.setattr(database, "complete_derived_artifact", real)
    assert worker(database, storage, voice_settings, voice).process_one(job_id=job_id)
    assert len(voice.calls) == 1
    assert database.get_ai_job(source[0], job_id).status == "succeeded"


def test_disable_and_duration_limits_fail_before_queue(
    api, source, database, storage, voice_settings
):
    from intentcut.backend.transcription.service import (
        TranscriptionRequest,
        TranscriptionService,
    )

    body = TranscriptionRequest(request_id=uuid4(), artifact_id=source[1].id)
    for settings, expected in [
        (
            voice_settings.model_copy(update={"voice_transcription_enabled": False}),
            "transcription_unavailable",
        ),
        (
            voice_settings.model_copy(update={"voice_max_duration_seconds": 1}),
            "processing_limit",
        ),
    ]:
        service = TranscriptionService(AIJobService(database, storage, settings))
        with pytest.raises(AIJobAPIError) as error:
            service.submit(source[0], body)
        assert error.value.code == expected


def test_lease_lost_during_inference_cannot_cache_or_publish(
    api, source, database, storage, voice_settings
):
    accepted = submit(api, source).json()
    job_id = UUID(accepted["id"])

    def lose_lease():
        old = database.get_ai_job(source[0], job_id)
        expire(database, old)
        database.recover_expired_ai_job(
            job_id=old.id, max_attempts=2, supported_job_types=(PIPELINE,)
        )

    voice = FakeVoice(on_call=lose_lease)
    executor = worker(database, storage, voice_settings, voice)
    assert executor.process_one(job_id=job_id)
    current = database.get_ai_job(source[0], job_id)
    assert current.status == "queued" and "voice_caption" not in current.request_payload
    assert database.list_ai_job_artifacts(source[0], job_id) == []
    assert executor.process_one(job_id=job_id)
    assert (
        database.get_ai_job(source[0], job_id).error_code
        == "transcription_outcome_unknown"
    )
    assert len(voice.calls) == 1


def test_crash_before_reservation_can_retry_once_safely(
    api, source, database, storage, voice_settings
):
    accepted = submit(api, source).json()
    job_id = UUID(accepted["id"])
    old = database.claim_next_ai_job(job_id=job_id)
    expire(database, old)
    database.recover_expired_ai_job(
        job_id=job_id, max_attempts=2, supported_job_types=(PIPELINE,)
    )
    voice = FakeVoice()
    assert worker(database, storage, voice_settings, voice).process_one(job_id=job_id)
    assert len(voice.calls) == 1
    assert database.get_ai_job(source[0], job_id).status == "succeeded"


def test_idempotent_concurrent_admission(
    api, source, database, storage, voice_settings
):
    from concurrent.futures import ThreadPoolExecutor

    from intentcut.backend.transcription.service import (
        TranscriptionRequest,
        TranscriptionService,
    )

    service = TranscriptionService(AIJobService(database, storage, voice_settings))

    def request(_):
        return service.submit(
            source[0],
            TranscriptionRequest(request_id=uuid4(), artifact_id=source[1].id),
        ).id

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(request, range(2)))
    assert len(set(results)) == 1


def test_admission_conflict_pending_and_project_budget(
    source, database, storage, voice_settings, processing_result
):
    from intentcut.backend.transcription.service import (
        TranscriptionRequest,
        TranscriptionService,
    )

    project, artifact = source
    base = database.create_ai_job(project, {"pipeline_version": "uploaded_v1"})
    old = database.claim_next_ai_job(job_id=base.id)
    assert AIArtifactPublisher(storage).publish_and_complete(
        database, project, old.id, old.lease_token, processing_result
    )
    other = next(
        a for a in database.list_ai_job_artifacts(project, old.id) if a.kind == "video"
    )
    service = TranscriptionService(AIJobService(database, storage, voice_settings))
    request_id = uuid4()
    service.submit(
        project, TranscriptionRequest(request_id=request_id, artifact_id=artifact.id)
    )
    with pytest.raises(AIJobAPIError) as error:
        service.submit(
            project, TranscriptionRequest(request_id=request_id, artifact_id=other.id)
        )
    assert error.value.code == "request_conflict"
    with pytest.raises(AIJobAPIError) as error:
        service.submit(
            project, TranscriptionRequest(request_id=uuid4(), artifact_id=other.id)
        )
    assert error.value.code == "transcription_pending"
    capped = TranscriptionService(
        AIJobService(
            database,
            storage,
            voice_settings.model_copy(update={"voice_max_jobs_per_project": 1}),
        )
    )
    with pytest.raises(AIJobAPIError) as error:
        capped.submit(
            project, TranscriptionRequest(request_id=uuid4(), artifact_id=other.id)
        )
    assert error.value.code == "transcription_limit" and error.value.status == 429


def test_reservation_commit_ack_loss_prevents_http_and_automatic_retry(
    api,
    source,
    database,
    storage,
    voice_settings,
    monkeypatch,
):
    from sqlalchemy.exc import SQLAlchemyError

    accepted = submit(api, source).json()
    job_id = UUID(accepted["id"])
    factory = database._sessions

    def uncertain_sessions():
        session = factory()
        commit = session.commit

        def lose_ack():
            commit()  # Real durable commit, followed by injected ACK failure.
            raise SQLAlchemyError("injected acknowledgement loss")

        session.commit = lose_ack
        return session

    uncertain_sessions.begin = factory.begin
    monkeypatch.setattr(database, "_sessions", uncertain_sessions)
    voice = FakeVoice()
    assert worker(database, storage, voice_settings, voice).process_one(job_id=job_id)
    assert voice.calls == []  # HTTP must not follow an uncertain reservation.
    monkeypatch.setattr(database, "_sessions", factory)
    current = database.get_ai_job(source[0], job_id)
    assert current.status == "running"
    assert current.request_payload["voice_call_started"] is True
    expire(database, current)
    database.recover_expired_ai_job(
        job_id=job_id, max_attempts=2, supported_job_types=(PIPELINE,)
    )
    assert worker(database, storage, voice_settings, voice).process_one(job_id=job_id)
    assert voice.calls == []
    assert (
        database.get_ai_job(source[0], job_id).error_code
        == "transcription_outcome_unknown"
    )
