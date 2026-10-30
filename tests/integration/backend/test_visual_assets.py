"""Real PNG publication/frame extraction with a mocked Muse Image provider."""

import hashlib
import subprocess
from datetime import timedelta
from pathlib import Path
from uuid import UUID, uuid4

import pytest
import test_voice_transcription as footage
from fastapi.testclient import TestClient
from pydantic import SecretStr
from sqlalchemy import func, text, update

from intentcut.backend.ai_artifacts import AIArtifactPublisher
from intentcut.backend.ai_job_service import AIJobService
from intentcut.backend.ai_worker import AIJobWorker
from intentcut.backend.app import create_app
from intentcut.backend.contracts import AIProcessingError, JobLeaseLost
from intentcut.backend.storage.database_models import AIJob
from intentcut.backend.visuals.processor import VisualProcessor
from intentcut.backend.visuals.repository import PIPELINE, reserve_call

source = footage.source
audio_videos = footage.audio_videos

pytestmark = [pytest.mark.integration, pytest.mark.postgres]


@pytest.fixture
def image_bytes(tmp_path):
    path = tmp_path / "valid-output.png"
    subprocess.run(
        [
            "ffmpeg",
            "-v",
            "error",
            "-f",
            "lavfi",
            "-i",
            "color=red:s=64x32",
            "-frames:v",
            "1",
            "-threads",
            "1",
            "-n",
            str(path),
        ],
        check=True,
        capture_output=True,
        timeout=30,
    )
    return path.read_bytes()


@pytest.fixture
def image_settings(settings):
    return settings.model_copy(
        update={
            "image_generation_enabled": True,
            "ai_jobs_local_enabled": True,
            "model_api_key": SecretStr("fake-image-key"),
        }
    )


@pytest.fixture
def api(image_settings, database, storage):
    with TestClient(
        create_app(image_settings, database=database, storage=storage),
        base_url="http://127.0.0.1:8000",
        client=("127.0.0.1", 12345),
    ) as client:
        yield client


def path(project):
    return f"/projects/{project}/ai-jobs/visuals"


def submit(api, project, **changes):
    return api.post(
        path(project),
        json={
            "request_id": str(uuid4()),
            "prompt": "Fixture cover",
            "preset": "cover",
            **changes,
        },
    )


class Provider:
    def __init__(self, data, callback=None, code=None):
        self.data, self.calls, self.callback, self.code = data, [], callback, code

    def generate(self, prompt, preset, job_id, source, content_type):
        self.calls.append(
            (
                prompt,
                preset,
                job_id,
                source.read_bytes() if source else None,
                content_type,
            )
        )
        if self.callback:
            self.callback()
        if self.code:
            raise AIProcessingError(self.code)
        return self.data


def worker(database, storage, settings, provider):
    return AIJobWorker(
        database,
        VisualProcessor(AIJobService(database, storage, settings), provider),
        artifact_publisher=AIArtifactPublisher(storage),
    )


def test_generate_publish_download_cover_and_reload(
    api, database, storage, image_settings, image_bytes
):
    project = database.create_project("Images").id
    request_id = str(uuid4())
    accepted = submit(api, project, request_id=request_id)
    assert accepted.status_code == 202, accepted.text
    job_id = UUID(accepted.json()["id"])

    def callback():
        job = database.get_ai_job(project, job_id)
        assert job.request_payload["image_call_started"] is True
        assert database.heartbeat_ai_job(project, job_id, job.lease_token)

    provider = Provider(image_bytes, callback)
    executor = worker(database, storage, image_settings, provider)
    assert executor.supported_job_types == (PIPELINE,)
    assert executor.process_one(job_id=job_id)
    assert len(provider.calls) == 1
    status = api.get(accepted.json()["status_url"]).json()
    assert status["status"] == "succeeded" and "request_payload" not in status
    history = api.get(path(project)).json()
    item = history["items"][0]
    assert item["model"] == "muse-image-1.0" and item["operation"] == "generate"
    assert item["source_artifact_id"] is None
    rows = database.list_ai_job_artifacts(project, job_id)
    assert len(rows) == 1 and rows[0].kind == "image"
    artifact = rows[0]
    assert artifact.sha256 == hashlib.sha256(image_bytes).hexdigest()
    download = api.get(f"/projects/{project}/ai-jobs/{job_id}/artifacts/{artifact.id}")
    assert (
        download.status_code == 200
        and download.content == image_bytes
        and download.headers["content-type"] == "image/png"
    )
    cover = api.put(
        path(project) + "/cover",
        json={"artifact_id": str(artifact.id), "expected_revision": 0},
    )
    assert cover.status_code == 200 and cover.json()["revision"] == 1
    assert api.get(path(project)).json()["cover"]["artifact_id"] == str(artifact.id)
    assert (
        api.put(
            path(project) + "/cover",
            json={"artifact_id": str(artifact.id), "expected_revision": 0},
        ).status_code
        == 409
    )
    assert submit(api, project, request_id=request_id).json()["id"] == str(job_id)
    assert submit(api, project).json()["id"] == str(job_id)
    assert not executor.process_one(job_id=job_id)


def test_edit_authorized_video_frame_and_image_lineage(
    api, source, database, storage, image_settings, image_bytes
):
    project, parent = source
    accepted = submit(
        api,
        project,
        operation="edit",
        source_artifact_id=str(parent.id),
        frame_seconds=0.5,
    )
    assert accepted.status_code == 202, accepted.text
    provider = Provider(image_bytes)
    job_id = UUID(accepted.json()["id"])
    assert worker(database, storage, image_settings, provider).process_one(
        job_id=job_id
    )
    assert (
        provider.calls[0][3].startswith(b"\x89PNG")
        and provider.calls[0][4] == "image/png"
    )
    row = database.list_ai_job_artifacts(project, job_id)[0]
    assert row.parent_artifact_id == parent.id and row.parent_sha256 == parent.sha256
    history = api.get(path(project)).json()["items"][0]
    assert history["frame_seconds"] == 0.5 and history["source_artifact_id"] == str(
        parent.id
    )
    second = submit(
        api,
        project,
        operation="edit",
        source_artifact_id=str(row.id),
        prompt="Different edit",
    )
    assert second.status_code == 202
    assert worker(database, storage, image_settings, provider).process_one(
        job_id=UUID(second.json()["id"])
    )
    assert provider.calls[1][3] == image_bytes


def test_cross_project_and_invalid_reference_rejected(api, source, database):
    project, parent = source
    other = database.create_project("Other").id
    assert (
        submit(
            api,
            other,
            operation="edit",
            source_artifact_id=str(parent.id),
            frame_seconds=0,
        ).status_code
        == 404
    )
    assert (
        submit(
            api,
            project,
            operation="edit",
            source_artifact_id=str(parent.id),
            frame_seconds=5,
        ).status_code
        == 422
    )
    assert (
        submit(
            api, project, operation="edit", source_artifact_id=str(parent.id)
        ).status_code
        == 422
    )
    assert (
        api.put(
            path(other) + "/cover",
            json={"artifact_id": str(parent.id), "expected_revision": 0},
        ).status_code
        == 404
    )


@pytest.mark.parametrize(
    "code", ["image_outcome_unknown", "provider_unavailable", "image_rate_limited"]
)
def test_provider_failure_has_no_partial_and_no_duplicate_call(
    api, database, storage, image_settings, image_bytes, code
):
    project = database.create_project("Failure").id
    job_id = UUID(submit(api, project).json()["id"])
    provider = Provider(image_bytes, code=code)
    executor = worker(database, storage, image_settings, provider)
    assert executor.process_one(job_id=job_id)
    job = database.get_ai_job(project, job_id)
    assert job.status == "failed" and job.error_code == code
    assert database.list_ai_job_artifacts(project, job_id) == []
    assert submit(api, project).json()["id"] == str(job_id)
    assert len(provider.calls) == 1 and not executor.process_one(job_id=job_id)


def test_malformed_actual_image_cannot_publish(api, database, storage, image_settings):
    project = database.create_project("Invalid").id
    job_id = UUID(submit(api, project).json()["id"])
    provider = Provider(b"\x89PNG\r\n\x1a\nnot an image")
    assert worker(database, storage, image_settings, provider).process_one(
        job_id=job_id
    )
    assert database.get_ai_job(project, job_id).status == "failed"
    assert database.list_ai_job_artifacts(project, job_id) == []


def expire(database, job):
    with database.engine.begin() as connection:
        connection.execute(
            update(AIJob)
            .where(AIJob.id == job.id)
            .values(lease_expires_at=func.clock_timestamp() - timedelta(seconds=1))
        )


def test_reserved_crash_recovery_never_repeats_inference(
    api, database, storage, image_settings, image_bytes
):
    project = database.create_project("Recovery").id
    job_id = UUID(submit(api, project).json()["id"])
    old = database.claim_next_ai_job(job_id=job_id)
    reserve_call(database, old)
    expire(database, old)
    database.recover_expired_ai_job(
        job_id=job_id, max_attempts=2, supported_job_types=(PIPELINE,)
    )
    provider = Provider(image_bytes)
    assert worker(database, storage, image_settings, provider).process_one(
        job_id=job_id
    )
    assert (
        provider.calls == []
        and database.get_ai_job(project, job_id).error_code == "image_outcome_unknown"
    )
    with pytest.raises(JobLeaseLost):
        reserve_call(database, old)


def test_validated_cache_recovers_publication_without_payment(
    api, database, storage, image_settings, image_bytes, monkeypatch
):
    from intentcut.backend.shared.persistence_errors import CommitOutcomeUnknown

    project = database.create_project("Cached").id
    job_id = UUID(submit(api, project).json()["id"])
    original = database.complete_derived_artifact

    def uncertain(*args):
        raise CommitOutcomeUnknown()

    monkeypatch.setattr(database, "complete_derived_artifact", uncertain)
    provider = Provider(image_bytes)
    assert worker(database, storage, image_settings, provider).process_one(
        job_id=job_id
    )
    job = database.get_ai_job(project, job_id)
    assert "image_cache" in job.request_payload
    expire(database, job)
    database.recover_expired_ai_job(
        job_id=job_id, max_attempts=2, supported_job_types=(PIPELINE,)
    )
    monkeypatch.setattr(database, "complete_derived_artifact", original)
    assert worker(database, storage, image_settings, provider).process_one(
        job_id=job_id
    )
    assert (
        len(provider.calls) == 1
        and database.get_ai_job(project, job_id).status == "succeeded"
    )


def test_migration_idempotent(database):
    sql = Path("scripts/migrations/006_project_covers.sql").read_text()
    with database.engine.begin() as connection:
        connection.execute(text("DROP TABLE project_covers"))
        connection.execute(text(sql))
        connection.execute(text(sql))
        assert (
            connection.execute(text("SELECT count(*) FROM project_covers")).scalar_one()
            == 0
        )
