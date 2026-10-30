"""Isolated PostgreSQL + real FFmpeg; no network providers or demo DB writes."""

import hashlib
import json
import subprocess
from datetime import timedelta
from pathlib import Path
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, text, update

from intentcut.backend.ai_artifacts import AIArtifactPublisher
from intentcut.backend.ai_job_service import AIJobAPIError, AIJobService
from intentcut.backend.ai_worker import AIJobWorker
from intentcut.backend.app import create_app
from intentcut.backend.artifacts.derived import (
    ArtifactParent,
    CaptionArtifactResult,
    ImageArtifactResult,
    VideoRenditionResult,
)
from intentcut.backend.jobs.dispatch import JobDispatcher, JobRegistration, JobType
from intentcut.backend.shared.persistence_errors import CommitOutcomeUnknown
from intentcut.backend.storage.database_models import AIJob
from intentcut.media.models import MediaProcessError

pytestmark = [pytest.mark.integration, pytest.mark.postgres]


@pytest.fixture
def client(settings, database, storage):
    local = settings.model_copy(update={"ai_jobs_local_enabled": True})
    app = create_app(local, database=database, storage=storage)
    with TestClient(
        app, base_url="http://127.0.0.1:8000", client=("127.0.0.1", 12345)
    ) as api:
        yield api


@pytest.fixture
def source(database, storage, processing_result):
    project = database.create_project("Derived fixtures")
    queued = database.create_ai_job(project.id, {"pipeline_version": "uploaded_v1"})
    claimed = database.claim_next_ai_job(job_id=queued.id)
    publisher = AIArtifactPublisher(storage)
    assert publisher.publish_and_complete(
        database, project.id, queued.id, claimed.lease_token, processing_result
    )
    parent = next(
        a
        for a in database.list_ai_job_artifacts(project.id, queued.id)
        if a.kind == "video"
    )
    return project.id, parent, publisher


def create_job(database, source, kind, *, parent=True, project_id=None):
    project, artifact, _ = source
    payload = {"pipeline_version": kind}
    if parent:
        payload.update(
            parent_artifact_id=str(artifact.id), parent_sha256=artifact.sha256
        )
    queued = database.create_ai_job(project_id or project, payload)
    return database.claim_next_ai_job(job_id=queued.id)


def output(tmp_path, source, kind, artifact_video_bytes):
    _, parent, _ = source
    ref = ArtifactParent(parent.id, parent.sha256)
    path = tmp_path / "output"
    if kind == "captions":
        # Deterministic fixture text, not an assertion that transcription ran.
        path.write_text(
            json.dumps(
                {
                    "schema_version": "captions-v1",
                    "duration_ms": 250,
                    "cues": [{"start_ms": 0, "end_ms": 200, "text": "Fixture"}],
                }
            )
        )
        return CaptionArtifactResult(path, ref)
    if kind == "rendition":
        path.write_bytes(artifact_video_bytes)
        return VideoRenditionResult(path, ref)
    subprocess.run(
        [
            "ffmpeg",
            "-v",
            "error",
            "-nostdin",
            "-f",
            "lavfi",
            "-i",
            "color=red:s=32x24",
            "-frames:v",
            "1",
            "-threads",
            "1",
            "-f",
            "image2",
            "-c:v",
            "png" if kind == "png" else "mjpeg",
            str(path),
        ],
        check=True,
        capture_output=True,
        timeout=30,
    )
    return ImageArtifactResult(path, ref)


def publish(database, source, job, result, **kwargs):
    return source[2].publish_and_complete(
        database, job.project_id, job.id, job.lease_token, result, **kwargs
    )


@pytest.mark.parametrize(
    "kind,pipeline,mime",
    [
        ("captions", "caption_artifact_v1", "application/json"),
        ("png", "image_artifact_v1", "image/png"),
        ("jpg", "image_artifact_v1", "image/jpeg"),
        ("rendition", "video_rendition_v1", "video/mp4"),
    ],
)
def test_publish_download_lineage_and_immutable_retry(
    database,
    storage,
    settings,
    client,
    source,
    tmp_path,
    artifact_video_bytes,
    kind,
    pipeline,
    mime,
):
    result = output(tmp_path, source, kind, artifact_video_bytes)
    job = create_job(database, source, pipeline)
    assert publish(database, source, job, result)
    rows = database.list_ai_job_artifacts(job.project_id, job.id)
    assert len(rows) == 1
    row = rows[0]
    assert row.content_type == mime
    assert row.parent_artifact_id == source[1].id
    assert row.parent_sha256 == source[1].sha256
    assert row.kind == {"png": "image", "jpg": "image"}.get(kind, kind)
    assert row.sha256 == hashlib.sha256(result.path.read_bytes()).hexdigest()
    original = result.path.read_bytes()
    service = AIJobService(database, storage, settings)
    with service.snapshot(job.project_id, row) as snapshot:
        assert snapshot.read() == original
    route = f"/projects/{job.project_id}/ai-jobs/{job.id}/artifacts"
    response = client.get(route)
    assert response.status_code == 200
    item = response.json()["items"][0]
    assert item["parent_artifact_id"] == str(source[1].id)
    assert "storage_key" not in item
    downloaded = client.get(item["download_url"])
    assert downloaded.status_code == 200
    assert downloaded.headers["content-type"].split(";")[0] == mime
    assert downloaded.content == original
    assert (
        client.get(
            item["download_url"].replace(str(job.project_id), str(uuid4()))
        ).status_code
        == 404
    )
    # A second completion is rejected and its newly allocated files compensated.
    assert not publish(database, source, job, result)
    assert [a.id for a in database.list_ai_job_artifacts(job.project_id, job.id)] == [
        row.id
    ]
    result.path.write_bytes(b"workspace changed")
    assert (storage.root / row.storage_key).read_bytes() == original
    (storage.root / row.storage_key).write_bytes(b"tampered")
    with pytest.raises(AIJobAPIError):
        service.snapshot(job.project_id, row)


@pytest.mark.parametrize(
    "damage",
    ["json", "large_json", "image", "gif", "video", "caption_duration", "symlink"],
)
def test_invalid_content_never_registers(
    database, storage, source, tmp_path, artifact_video_bytes, damage
):
    kind = (
        "png"
        if damage in {"image", "gif"}
        else "rendition"
        if damage == "video"
        else "captions"
    )
    pipeline = {
        "png": "image_artifact_v1",
        "rendition": "video_rendition_v1",
        "captions": "caption_artifact_v1",
    }[kind]
    result = output(tmp_path, source, kind, artifact_video_bytes)
    job = create_job(database, source, pipeline)
    data = {
        "json": b"{",
        "large_json": b" " * (1024 * 1024 + 1),
        "image": b"\x89PNG\r\n\x1a\ninvalid",
        "gif": b"GIF89a",
        "video": b"ftypinvalid",
        "caption_duration": (
            b'{"schema_version":"captions-v1","duration_ms":999,"cues":[]}'
        ),
    }
    if damage == "symlink":
        destination = tmp_path / "target"
        result.path.rename(destination)
        result.path.symlink_to(destination)
    else:
        result.path.write_bytes(data[damage])
    with pytest.raises((ValueError, OSError, MediaProcessError)):
        publish(database, source, job, result)
    assert database.list_ai_job_artifacts(job.project_id, job.id) == []
    assert database.get_ai_job(job.project_id, job.id).status == "running"
    assert list((storage.root / ".staging").iterdir()) == []
    assert len(list((storage.root / "projects").glob("*/*/original"))) == 2


@pytest.mark.parametrize(
    "damage", ["cross_project", "hash", "parent_bytes", "wrong_pipeline", "job_parent"]
)
def test_invalid_parent_or_output_contract(
    database, storage, source, tmp_path, artifact_video_bytes, damage
):
    result = output(tmp_path, source, "rendition", artifact_video_bytes)
    project = database.create_project("Other").id if damage == "cross_project" else None
    job = create_job(
        database,
        source,
        "image_artifact_v1" if damage == "wrong_pipeline" else "video_rendition_v1",
        project_id=project,
    )
    if damage == "hash":
        result = VideoRenditionResult(
            result.path, ArtifactParent(source[1].id, "0" * 64)
        )
    elif damage == "parent_bytes":
        (storage.root / source[1].storage_key).write_bytes(b"tampered")
    elif damage == "job_parent":
        with database.engine.begin() as connection:
            connection.execute(
                update(AIJob)
                .where(AIJob.id == job.id)
                .values(request_payload={"pipeline_version": "video_rendition_v1"})
            )
    with pytest.raises(ValueError):
        publish(database, source, job, result)
    assert database.list_ai_job_artifacts(job.project_id, job.id) == []
    assert len(list((storage.root / "projects").glob("*/*/original"))) == 2


def expire(database, job):
    with database.engine.begin() as connection:
        connection.execute(
            update(AIJob)
            .where(AIJob.id == job.id)
            .values(lease_expires_at=func.clock_timestamp() - timedelta(seconds=1))
        )


def test_crash_recovery_fences_old_worker_and_clears_progress(
    database, storage, source, tmp_path, artifact_video_bytes
):
    result = output(tmp_path, source, "captions", artifact_video_bytes)
    old = create_job(database, source, "caption_artifact_v1")
    assert database.update_ai_job_progress(
        old.project_id, old.id, old.lease_token, "publishing_artifacts"
    )
    expire(database, old)
    recovered = database.recover_expired_ai_job(
        job_id=old.id, max_attempts=2, supported_job_types=("caption_artifact_v1",)
    )
    assert recovered.status == "queued" and recovered.progress is None
    fresh = database.claim_next_ai_job(
        job_id=old.id, supported_job_types=("caption_artifact_v1",)
    )
    assert fresh.lease_token != old.lease_token
    assert not publish(database, source, old, result)
    assert database.list_ai_job_artifacts(old.project_id, old.id) == []
    assert publish(database, source, fresh, result)
    assert not database.fail_ai_job(
        old.project_id, old.id, old.lease_token, "processing_failed"
    )
    assert database.get_ai_job(old.project_id, old.id).status == "succeeded"


@pytest.mark.parametrize("fence", ["token", "expired", "ownership", "failed"])
def test_publication_fencing(
    database, storage, source, tmp_path, artifact_video_bytes, fence
):
    result = output(tmp_path, source, "captions", artifact_video_bytes)
    job = create_job(database, source, "caption_artifact_v1")
    kwargs = {}
    if fence == "token":
        job.lease_token = uuid4()
    elif fence == "expired":
        expire(database, job)
    elif fence == "failed":
        assert database.fail_ai_job(
            job.project_id, job.id, job.lease_token, "processing_failed"
        )
    else:
        kwargs["owns_lease"] = lambda: False
    assert not publish(database, source, job, result, **kwargs)
    assert database.list_ai_job_artifacts(job.project_id, job.id) == []
    assert len(list((storage.root / "projects").glob("*/*/original"))) == 2


@pytest.mark.parametrize("committed", [True, False])
def test_uncertain_commit_retains_files_and_reconciles(
    database, storage, source, tmp_path, artifact_video_bytes, monkeypatch, committed
):
    result = output(tmp_path, source, "captions", artifact_video_bytes)
    job = create_job(database, source, "caption_artifact_v1")
    original = database.complete_derived_artifact
    captured = []

    def uncertain(project, job_id, token, artifact):
        captured.append(artifact)
        if committed:
            assert original(project, job_id, token, artifact)
        raise CommitOutcomeUnknown

    monkeypatch.setattr(database, "complete_derived_artifact", uncertain)
    if committed:
        assert publish(database, source, job, result)
    else:
        with pytest.raises(CommitOutcomeUnknown):
            publish(database, source, job, result)
        assert database.list_ai_job_artifacts(job.project_id, job.id) == []
    assert (storage.root / captured[0].storage_key).exists()


def test_registered_worker_executes_derived_only(
    database, storage, source, tmp_path, artifact_video_bytes
):
    result = output(tmp_path, source, "captions", artifact_video_bytes)
    # Queue through the repository, not an inference endpoint.
    parent = source[1]
    job = database.create_ai_job(
        source[0],
        {
            "pipeline_version": "caption_artifact_v1",
            "parent_artifact_id": str(parent.id),
            "parent_sha256": parent.sha256,
        },
    )
    dispatcher = JobDispatcher(
        [
            JobRegistration(
                JobType.CAPTION_ARTIFACT, lambda job: result, CaptionArtifactResult
            )
        ]
    )
    worker = AIJobWorker(database, dispatcher, artifact_publisher=source[2])
    assert worker.process_one(job_id=job.id)
    assert database.get_ai_job(source[0], job.id).status == "succeeded"
    assert len(database.list_ai_job_artifacts(source[0], job.id)) == 1


def test_migration_from_legacy_preserves_rows_and_is_idempotent(database, source):
    migration = Path("scripts/migrations/004_derived_artifacts.sql").read_text()
    with database.engine.begin() as connection:
        before = connection.execute(
            text("SELECT id, sha256 FROM ai_job_artifacts ORDER BY id")
        ).all()
        # Reconstruct the pre-Batch-2 artifact shape in this isolated test schema.
        connection.execute(
            text("ALTER TABLE ai_job_artifacts DROP COLUMN content_type CASCADE")
        )
        connection.execute(
            text("ALTER TABLE ai_job_artifacts DROP COLUMN parent_artifact_id CASCADE")
        )
        connection.execute(
            text("ALTER TABLE ai_job_artifacts DROP COLUMN parent_sha256 CASCADE")
        )
        connection.execute(
            text("ALTER TABLE ai_job_artifacts DROP CONSTRAINT artifact_kind")
        )
        connection.execute(
            text(
                "ALTER TABLE ai_job_artifacts ADD CONSTRAINT artifact_kind "
                "CHECK (kind IN ('video','storyboard'))"
            )
        )
        connection.execute(text(migration))
        connection.execute(text(migration))
        assert (
            connection.execute(
                text("SELECT id, sha256 FROM ai_job_artifacts ORDER BY id")
            ).all()
            == before
        )
        constraints = (
            connection.execute(
                text(
                    "SELECT conname FROM pg_constraint "
                    "WHERE conrelid = 'ai_job_artifacts'::regclass"
                )
            )
            .scalars()
            .all()
        )
        assert {
            "artifact_kind",
            "artifact_parent_fk",
            "artifact_parent_pair",
            "artifact_content_type",
        } <= set(constraints)


def test_image_without_parent_is_allowed_but_caption_is_not(
    database, source, tmp_path, artifact_video_bytes
):
    result = output(tmp_path, source, "png", artifact_video_bytes)
    job = create_job(database, source, "image_artifact_v1", parent=False)
    assert publish(database, source, job, ImageArtifactResult(result.path))
    row = database.list_ai_job_artifacts(job.project_id, job.id)[0]
    assert row.parent_artifact_id is None and row.parent_sha256 is None
    job = create_job(database, source, "caption_artifact_v1", parent=False)
    with pytest.raises(ValueError, match="Parent is required"):
        publish(database, source, job, CaptionArtifactResult(result.path, None))


def test_competing_publishers_register_one_output(
    database, storage, source, tmp_path, artifact_video_bytes
):
    from concurrent.futures import ThreadPoolExecutor

    result = output(tmp_path, source, "captions", artifact_video_bytes)
    job = create_job(database, source, "caption_artifact_v1")
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(
            pool.map(lambda _: publish(database, source, job, result), range(2))
        )
    assert sorted(results) == [False, True]
    assert len(database.list_ai_job_artifacts(job.project_id, job.id)) == 1
    assert len(list((storage.root / "projects").glob("*/*/original"))) == 3


def test_lease_loss_after_file_publication_removes_unregistered_file(
    database, storage, source, tmp_path, artifact_video_bytes
):
    result = output(tmp_path, source, "captions", artifact_video_bytes)
    job = create_job(database, source, "caption_artifact_v1")
    checks = iter([True, False])
    assert not publish(database, source, job, result, owns_lease=lambda: next(checks))
    assert database.list_ai_job_artifacts(job.project_id, job.id) == []
    assert len(list((storage.root / "projects").glob("*/*/original"))) == 2


def test_worker_validation_failure_cannot_publish_partial_output(
    database, source, tmp_path
):
    path = tmp_path / "invalid-captions"
    path.write_bytes(b"not JSON")
    parent = source[1]
    job = database.create_ai_job(
        source[0],
        {
            "pipeline_version": "caption_artifact_v1",
            "parent_artifact_id": str(parent.id),
            "parent_sha256": parent.sha256,
        },
    )
    result = CaptionArtifactResult(path, ArtifactParent(parent.id, parent.sha256))
    dispatcher = JobDispatcher(
        [
            JobRegistration(
                JobType.CAPTION_ARTIFACT, lambda job: result, CaptionArtifactResult
            )
        ]
    )
    worker = AIJobWorker(database, dispatcher, artifact_publisher=source[2])
    assert worker.process_one(job_id=job.id)
    failed = database.get_ai_job(source[0], job.id)
    assert failed.status == "failed" and failed.error_code == "processing_failed"
    assert failed.progress is None
    assert database.list_ai_job_artifacts(source[0], job.id) == []


def test_derived_completion_rechecks_expiry_after_insert(
    database, source, tmp_path, artifact_video_bytes
):
    import time

    from sqlalchemy import event

    result = output(tmp_path, source, "captions", artifact_video_bytes)
    job = create_job(database, source, "caption_artifact_v1")
    # Recheck PostgreSQL wall clock after INSERT, not just at transaction start.
    with database.engine.begin() as connection:
        connection.execute(
            update(AIJob)
            .where(AIJob.id == job.id)
            .values(lease_expires_at=func.clock_timestamp() + timedelta(seconds=1))
        )

    delayed = []

    def delay_insert(connection, cursor, statement, parameters, context, executemany):
        if statement.startswith("INSERT INTO ai_job_artifacts"):
            delayed.append(True)
            time.sleep(1.1)

    event.listen(database.engine, "after_cursor_execute", delay_insert)
    try:
        assert not publish(database, source, job, result)
    finally:
        event.remove(database.engine, "after_cursor_execute", delay_insert)
    assert delayed == [True]
    assert database.list_ai_job_artifacts(job.project_id, job.id) == []
