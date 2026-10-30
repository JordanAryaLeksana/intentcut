"""Real saved-revision FFmpeg exports; only transcription evidence is synthetic."""

import hashlib
import json
import subprocess
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from pathlib import Path
from uuid import UUID

import pytest
import test_voice_transcription as fixtures
from sqlalchemy import func, text, update

from intentcut.backend.ai_artifacts import AIArtifactPublisher
from intentcut.backend.ai_job_service import AIJobService
from intentcut.backend.ai_worker import AIJobWorker
from intentcut.backend.artifacts.derived import ArtifactParent, CaptionArtifactResult
from intentcut.backend.captions.processor import CaptionBurnProcessor
from intentcut.backend.captions.render import frame_info
from intentcut.backend.storage.database_models import AIJob

voice_settings = fixtures.voice_settings
api = fixtures.api
source = fixtures.source
audio_videos = fixtures.audio_videos

pytestmark = [pytest.mark.integration, pytest.mark.postgres]


@pytest.fixture
def transcript(database, storage, source, tmp_path):
    project, parent = source
    job = database.create_ai_job(
        project,
        {
            "pipeline_version": "caption_artifact_v1",
            "parent_artifact_id": str(parent.id),
            "parent_sha256": parent.sha256,
        },
    )
    claimed = database.claim_next_ai_job(job_id=job.id)
    path = tmp_path / "fixture-captions.json"
    path.write_text(
        json.dumps(
            {
                "schema_version": "captions-v1",
                "duration_ms": 2000,
                "cues": [{"start_ms": 300, "end_ms": 1500, "text": "HELLO EDITOR"}],
            }
        )
    )
    assert AIArtifactPublisher(storage).publish_and_complete(
        database,
        project,
        job.id,
        claimed.lease_token,
        CaptionArtifactResult(path, ArtifactParent(parent.id, parent.sha256)),
    )
    artifact = database.list_ai_job_artifacts(project, job.id)[0]
    return project, parent, artifact


def endpoint(project, tail=""):
    return f"/projects/{project}/ai-jobs/caption-sets{tail}"


def create(api, transcript):
    response = api.post(
        endpoint(transcript[0]),
        json={"transcription_artifact_id": str(transcript[2].id)},
    )
    assert response.status_code == 200, response.text
    return response.json()


def edit(api, saved, text="FIRST REVISION", enabled=True):
    return api.put(
        endpoint(saved["project_id"], f"/{saved['id']}"),
        json={
            "expected_revision": saved["revision"],
            "cues": [{"index": 0, "text": text, "enabled": enabled}],
        },
    )


def export(api, saved):
    result = api.post(
        endpoint(saved["project_id"], f"/{saved['id']}/exports"),
        json={"expected_revision": saved["revision"]},
    )
    assert result.status_code == 202, result.text
    return UUID(result.json()["id"])


def executor(database, storage, settings):
    return AIJobWorker(
        database,
        CaptionBurnProcessor(AIJobService(database, storage, settings)),
        artifact_publisher=AIArtifactPublisher(storage),
    )


def whites(path, at):
    raw = subprocess.run(
        [
            "ffmpeg",
            "-v",
            "error",
            "-ss",
            str(at),
            "-i",
            str(path),
            "-frames:v",
            "1",
            "-pix_fmt",
            "rgb24",
            "-f",
            "rawvideo",
            "-",
        ],
        check=True,
        capture_output=True,
        timeout=30,
    ).stdout
    return sum(all(v > 190 for v in raw[i : i + 3]) for i in range(0, len(raw), 3))


def test_save_reload_conflict_and_immutable_original(api, transcript, storage):
    saved = create(api, transcript)
    original = (storage.root / transcript[2].storage_key).read_bytes()
    assert create(api, transcript)["id"] == saved["id"]
    changed = edit(api, saved, "Changed text").json()
    assert changed["revision"] == 2 and changed["cues"][0]["text"] == "Changed text"
    reloaded = api.get(endpoint(transcript[0], f"/{saved['id']}")).json()
    assert reloaded == changed
    assert edit(api, saved, "Stale overwrite").status_code == 409
    assert (storage.root / transcript[2].storage_key).read_bytes() == original
    assert changed["parent_artifact_id"] == str(transcript[1].id)
    assert changed["parent_sha256"] == transcript[1].sha256
    assert changed["cues"][0]["start_ms"] == saved["cues"][0]["start_ms"]


def test_real_visible_export_exact_revision_and_source_preservation(
    api, transcript, database, storage, voice_settings
):
    saved = edit(api, create(api, transcript)).json()
    job_id = export(api, saved)
    assert export(api, saved) == job_id
    latest = edit(api, saved, "SECOND REVISION").json()
    source_path = storage.root / transcript[1].storage_key
    original = source_path.read_bytes()
    worker = executor(database, storage, voice_settings)
    assert worker.supported_job_types == ("caption_burn_v1",)
    assert worker.process_one(job_id=job_id)
    assert database.get_ai_job(transcript[0], job_id).status == "succeeded"
    output = database.list_ai_job_artifacts(transcript[0], job_id)[0]
    path = storage.root / output.storage_key
    assert frame_info(path) == frame_info(source_path) == (48, 24)
    assert hashlib.sha256(path.read_bytes()).hexdigest() != transcript[1].sha256
    assert source_path.read_bytes() == original
    assert whites(source_path, 0.8) == 0
    assert (
        whites(path, 0.8) > 20
    )  # Actual visible glyphs; success exit alone is insufficient.
    assert whites(path, 0.1) == 0  # No early subtitle / timing offset.
    files = list((storage.root / ".jobs" / str(job_id)).glob("attempt_*/cue_*.txt"))
    assert files and "FIRST REVISION" in files[0].read_text()
    assert "SECOND" not in files[0].read_text()
    metadata = api.get(f"/projects/{transcript[0]}/ai-jobs/{job_id}/artifacts").json()[
        "items"
    ][0]
    assert metadata["caption_revision"] == saved["revision"] == 2
    assert metadata["caption_set_id"] == saved["id"]
    assert metadata["parent_artifact_id"] == str(transcript[1].id)
    assert api.get(metadata["download_url"]).content == path.read_bytes()
    assert (
        api.get(endpoint(transcript[0], f"/{saved['id']}")).json()["revision"]
        == latest["revision"]
    )
    # A separate saved revision is a separate immutable output.
    new_id = export(api, latest)
    assert new_id != job_id and worker.process_one(job_id=new_id)
    assert len(database.list_ai_job_artifacts(transcript[0], job_id)) == 1
    assert (
        database.list_ai_job_artifacts(transcript[0], new_id)[0].sha256 != output.sha256
    )

    # Decoder hash verifies that copied AAC audio has not changed.
    def audio_hash(p):
        return subprocess.run(
            [
                "ffmpeg",
                "-v",
                "error",
                "-i",
                str(p),
                "-map",
                "0:a:0",
                "-f",
                "hash",
                "-hash",
                "sha256",
                "-",
            ],
            check=True,
            capture_output=True,
            timeout=30,
        ).stdout

    assert audio_hash(source_path) == audio_hash(path)


@pytest.mark.parametrize(
    "attack", ["control", "timestamp", "index", "missing", "blank"]
)
def test_invalid_caption_edits_rejected(api, transcript, attack):
    saved = create(api, transcript)
    cue = {"index": 0, "text": "plain", "enabled": True}
    if attack == "control":
        cue["text"] = "bad\x00text"
    elif attack == "timestamp":
        cue["start_ms"] = 0
    elif attack == "index":
        cue["index"] = 1
    elif attack == "blank":
        cue["text"] = " "
    response = api.put(
        endpoint(transcript[0], f"/{saved['id']}"),
        json={"expected_revision": 1, "cues": [] if attack == "missing" else [cue]},
    )
    assert response.status_code == 422, response.text
    assert api.get(endpoint(transcript[0], f"/{saved['id']}")).json()["revision"] == 1


def test_cross_project_and_wrong_source(api, transcript, database):
    saved = create(api, transcript)
    other = database.create_project("other").id
    assert api.get(endpoint(other, f"/{saved['id']}")).status_code == 404
    assert (
        api.put(
            endpoint(other, f"/{saved['id']}"),
            json={"expected_revision": 1, "cues": []},
        ).status_code
        == 404
    )
    assert (
        api.post(
            endpoint(other), json={"transcription_artifact_id": saved["id"]}
        ).status_code
        == 404
    )
    assert (
        api.post(
            endpoint(other, f"/{saved['id']}/exports"), json={"expected_revision": 1}
        ).status_code
        == 404
    )
    assert (
        api.post(
            endpoint(transcript[0]),
            json={"transcription_artifact_id": str(transcript[1].id)},
        ).status_code
        == 404
    )
    assert (
        api.get(
            f"/projects/{other}/ai-jobs/videos/{transcript[1].id}/captions"
        ).status_code
        == 404
    )


def test_disabled_cue_export_is_truthfully_unchanged(
    api, transcript, database, storage, voice_settings
):
    saved = edit(api, create(api, transcript), enabled=False).json()
    job_id = export(api, saved)
    assert executor(database, storage, voice_settings).process_one(job_id=job_id)
    result = database.list_ai_job_artifacts(transcript[0], job_id)[0]
    assert result.sha256 == transcript[1].sha256
    assert result.kind == "rendition"


def test_filter_syntax_is_literal_plain_text(
    api, transcript, database, storage, voice_settings
):
    literal = r"%{n} {\an8}"
    saved = edit(api, create(api, transcript), literal).json()
    job_id = export(api, saved)
    assert executor(database, storage, voice_settings).process_one(job_id=job_id)
    output = database.list_ai_job_artifacts(transcript[0], job_id)[0]
    assert whites(storage.root / output.storage_key, 0.8) > 20
    textfiles = list((storage.root / ".jobs" / str(job_id)).glob("attempt_*/cue_*.txt"))
    assert textfiles[0].read_text() == literal


def test_export_recovery_fences_expired_worker(
    api, transcript, database, storage, voice_settings
):
    saved = create(api, transcript)
    job_id = export(api, saved)
    old = database.claim_next_ai_job(job_id=job_id)
    result = CaptionBurnProcessor(AIJobService(database, storage, voice_settings))(old)
    with database.engine.begin() as connection:
        connection.execute(
            update(AIJob)
            .where(AIJob.id == job_id)
            .values(lease_expires_at=func.clock_timestamp() - timedelta(seconds=1))
        )
    assert (
        database.recover_expired_ai_job(
            job_id=job_id, max_attempts=2, supported_job_types=("caption_burn_v1",)
        ).status
        == "queued"
    )
    assert not AIArtifactPublisher(storage).publish_and_complete(
        database, transcript[0], job_id, old.lease_token, result
    )
    assert executor(database, storage, voice_settings).process_one(job_id=job_id)
    assert len(database.list_ai_job_artifacts(transcript[0], job_id)) == 1
    state = api.get(
        f"/projects/{transcript[0]}/ai-jobs/videos/{transcript[1].id}/captions"
    ).json()
    assert state["jobs"][0]["status"] == "succeeded"
    assert state["sets"][0]["id"] == saved["id"]


def test_concurrent_saves_have_one_winner(
    api, transcript, database, storage, voice_settings
):
    from intentcut.backend.ai_job_service import AIJobAPIError
    from intentcut.backend.captions.schemas import SaveCaptions
    from intentcut.backend.captions.service import CaptionService

    saved = create(api, transcript)
    service = CaptionService(AIJobService(database, storage, voice_settings))

    def save(label):
        try:
            return service.save(
                transcript[0],
                UUID(saved["id"]),
                SaveCaptions(
                    expected_revision=1,
                    cues=[{"index": 0, "text": label, "enabled": True}],
                ),
            ).revision
        except AIJobAPIError as error:
            return error.status

    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sorted(pool.map(save, ["ONE", "TWO"])) == [2, 409]


def test_migration_idempotency_and_preservation(database, api, transcript):
    saved = create(api, transcript)
    sql = Path("scripts/migrations/005_caption_sets.sql").read_text()
    with database.engine.begin() as connection:
        connection.execute(text(sql))
        connection.execute(text(sql))
        assert (
            connection.execute(
                text("SELECT revision FROM caption_sets WHERE id=:id"),
                {"id": saved["id"]},
            ).scalar_one()
            == 1
        )
        connection.execute(text("DROP TABLE caption_sets"))
        connection.execute(text("DROP INDEX uq_caption_export_revision"))
        connection.execute(text(sql))
        connection.execute(text(sql))
        assert (
            connection.execute(text("SELECT count(*) FROM caption_sets")).scalar_one()
            == 0
        )


def test_empty_transcript_create_save_and_export(
    api, transcript, database, storage, voice_settings, tmp_path
):
    project, parent, _ = transcript
    job = database.create_ai_job(
        project,
        {
            "pipeline_version": "caption_artifact_v1",
            "parent_artifact_id": str(parent.id),
            "parent_sha256": parent.sha256,
        },
    )
    claimed = database.claim_next_ai_job(job_id=job.id)
    path = tmp_path / "no-speech.json"
    path.write_text('{"schema_version":"captions-v1","duration_ms":2000,"cues":[]}')
    assert AIArtifactPublisher(storage).publish_and_complete(
        database,
        project,
        job.id,
        claimed.lease_token,
        CaptionArtifactResult(path, ArtifactParent(parent.id, parent.sha256)),
    )
    original = database.list_ai_job_artifacts(project, job.id)[0]
    saved = create(api, (project, parent, original))
    assert saved["cues"] == []
    response = api.put(
        endpoint(project, f"/{saved['id']}"), json={"expected_revision": 1, "cues": []}
    )
    assert response.status_code == 200
    job_id = export(api, response.json())
    assert executor(database, storage, voice_settings).process_one(job_id=job_id)
    assert database.list_ai_job_artifacts(project, job_id)[0].sha256 == parent.sha256


def test_parent_tamper_prevents_export_and_stale_revision_conflicts(
    api, transcript, storage
):
    saved = create(api, transcript)
    edit(api, saved)
    assert (
        api.post(
            endpoint(transcript[0], f"/{saved['id']}/exports"),
            json={"expected_revision": 1},
        ).status_code
        == 409
    )
    (storage.root / transcript[1].storage_key).write_bytes(b"modified media")
    assert (
        api.post(
            endpoint(transcript[0], f"/{saved['id']}/exports"),
            json={"expected_revision": 2},
        ).status_code
        == 503
    )


def test_failed_renderer_has_no_published_output(
    api, transcript, database, storage, voice_settings, monkeypatch, tmp_path
):
    import intentcut.backend.captions.render as renderer

    saved = create(api, transcript)
    job_id = export(api, saved)
    monkeypatch.setattr(renderer, "FONT", tmp_path / "absent-font.ttf")
    assert executor(database, storage, voice_settings).process_one(job_id=job_id)
    job = database.get_ai_job(transcript[0], job_id)
    assert job.status == "failed" and job.error_code == "caption_render_unsupported"
    assert database.list_ai_job_artifacts(transcript[0], job_id) == []


def test_disabled_blank_save_and_zero_cue_lineage_are_honest(
    api, transcript, database, storage, voice_settings
):
    saved = edit(api, create(api, transcript), "   ", False)
    assert saved.status_code == 200, saved.text
    job_id = export(api, saved.json())
    assert executor(database, storage, voice_settings).process_one(job_id=job_id)
    state = api.get(
        f"/projects/{transcript[0]}/ai-jobs/videos/{transcript[1].id}/captions"
    ).json()
    assert state["jobs"][0]["enabled_cues"] == 0
    assert (
        database.list_ai_job_artifacts(transcript[0], job_id)[0].sha256
        == transcript[1].sha256
    )
