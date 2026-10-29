"""HTTP contracts over real PostgreSQL and locally generated, published outputs."""

import hashlib
import json
import os
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select, update

from intentcut.backend.ai_artifacts import AIArtifactPublisher
from intentcut.backend.ai_worker import AIJobWorker
from intentcut.backend.app import create_app
from intentcut.backend.storage.database_models import AIJob, AIJobArtifact

pytestmark = [pytest.mark.integration, pytest.mark.postgres]


@pytest.fixture
def ai_client(settings, database, storage):
    settings = settings.model_copy(update={"ai_jobs_local_enabled": True})
    app = create_app(settings, database=database, storage=storage)
    with TestClient(
        app,
        base_url="http://127.0.0.1:8000",
        client=("127.0.0.1", 12345),
        raise_server_exceptions=False,
    ) as client:
        yield client


@pytest.fixture
def job(database):
    project = database.create_project("AI API")
    return database.create_ai_job(
        project.id,
        {"kind": "first_cut", "private": "/secret/workspace", "api_key": "private-key"},
    )


def job_url(job):
    return f"/projects/{job.project_id}/ai-jobs/{job.id}"


@pytest.fixture
def published(database, storage, processing_result, job):
    processing_result.storyboard_path.write_text(
        json.dumps(
            {
                "title": "/private/title",
                "rationale": "provider-secret",
                "source_media": "/private/clip.mp4",
                "workspace": "/secret/workspace",
                "metadata": {"api_key": "private-key"},
                "target_seconds": 10,
                "total_seconds": 0.25,
                "cuts": [
                    {
                        "window_index": 0,
                        "start_seconds": 0,
                        "end_seconds": 0.25,
                        "source_media": "C:\\private\\clip.mp4",
                        "editorial_reason": "A shot at /private/source.mp4",
                        "extra": {"token": "private-key"},
                    }
                ],
            }
        )
    )
    worker = AIJobWorker(
        database,
        lambda _: processing_result,
        artifact_publisher=AIArtifactPublisher(storage),
    )
    assert worker.process_one()
    return {
        artifact.kind: artifact
        for artifact in database.list_ai_job_artifacts(job.project_id, job.id)
    }


@pytest.mark.parametrize("state", ["queued", "running", "failed", "succeeded"])
def test_status_allowlist(ai_client, database, storage, processing_result, job, state):
    if state != "queued":
        claimed = database.claim_next_ai_job()
        if state == "failed":
            database.fail_ai_job(
                job.project_id, job.id, claimed.lease_token, "processing_failed"
            )
        elif state == "succeeded":
            assert AIArtifactPublisher(storage).publish_and_complete(
                database, job.project_id, job.id, claimed.lease_token, processing_result
            )
    response = ai_client.get(job_url(job))
    assert response.status_code == 200, response.text
    body = response.json()
    assert set(body) == {
        "id",
        "status",
        "created_at",
        "updated_at",
        "started_at",
        "finished_at",
        "attempt_count",
        "error_code",
        "progress",
    }
    assert body["status"] == state
    assert body["attempt_count"] == (0 if state == "queued" else 1)
    assert body["created_at"] and body["updated_at"]
    assert (body["started_at"] is not None) == (state != "queued")
    assert (body["finished_at"] is not None) == (state in {"failed", "succeeded"})
    assert body["error_code"] == ("processing_failed" if state == "failed" else None)
    assert "private" not in response.text and "lease" not in response.text
    assert response.headers["cache-control"] == "private, no-store"


@pytest.mark.parametrize(
    "code", ["worker_lease_expired", "/secret/traceback", "api_key"]
)
def test_safe_error_codes(ai_client, database, job, code):
    with database.engine.begin() as connection:
        connection.execute(
            update(AIJob)
            .where(AIJob.id == job.id)
            .values(status="failed", error_code=code)
        )
    expected = code if code == "worker_lease_expired" else "processing_failed"
    assert ai_client.get(job_url(job)).json()["error_code"] == expected


@pytest.mark.parametrize("suffix", ["", "/artifacts", "/artifacts/{artifact_id}"])
def test_missing_and_wrong_project(ai_client, database, job, published, suffix):
    suffix = suffix.format(artifact_id=published["video"].id)
    other = database.create_project("Other")
    paths = [
        f"/projects/{other.id}/ai-jobs/{job.id}{suffix}",
        f"/projects/{uuid4()}/ai-jobs/{job.id}{suffix}",
        f"/projects/{job.project_id}/ai-jobs/{uuid4()}{suffix}",
    ]
    for path in paths:
        response = ai_client.get(path)
        assert response.status_code == 404, response.text
        assert response.json() == {
            "code": "not_found",
            "message": "Resource not found.",
        }


def test_artifact_listing_and_downloads(
    ai_client, database, job, published, artifact_video_bytes, storage
):
    # An unregistered filesystem object must never appear in listing.
    orphan = storage.root / "projects" / str(job.project_id) / str(uuid4())
    orphan.mkdir()
    (orphan / "original").write_bytes(b"private orphan")
    response = ai_client.get(job_url(job) + "/artifacts")
    assert response.status_code == 200
    items = response.json()["items"]
    assert {item["kind"] for item in items} == {"storyboard", "video"}
    assert all(
        set(item) == {"id", "kind", "size_bytes", "download_url"} for item in items
    )
    assert "storage" not in response.text and "original" not in response.text
    for item in items:
        download = ai_client.get(item["download_url"])
        assert download.status_code == 200, download.text
        assert download.headers["cache-control"] == "private, no-store"
        assert download.headers["x-content-type-options"] == "nosniff"
        assert int(download.headers["content-length"]) == len(download.content)
        extension = "mp4" if item["kind"] == "video" else "json"
        assert download.headers["content-disposition"] == (
            f'attachment; filename="{item["id"]}.{extension}"'
        )
        if item["kind"] == "video":
            assert download.headers["content-type"] == "video/mp4"
            assert download.content == artifact_video_bytes
        else:
            assert download.headers["content-type"] == "application/json"
            assert download.json() == {
                "target_seconds": 10.0,
                "total_seconds": 0.25,
                "cuts": [
                    {"window_index": 0, "start_seconds": 0.0, "end_seconds": 0.25}
                ],
            }
            assert b"private" not in download.content
    # No artifact under another job, even in the same project.
    second = database.create_ai_job(job.project_id, {"kind": "first_cut"})
    assert ai_client.get(job_url(second) + "/artifacts").json() == {"items": []}
    assert (
        ai_client.get(
            job_url(second) + f"/artifacts/{published['video'].id}"
        ).status_code
        == 404
    )
    assert ai_client.get(job_url(job) + f"/artifacts/{uuid4()}").status_code == 404


@pytest.mark.parametrize(
    "fault",
    [
        "missing",
        "truncated",
        "checksum",
        "symlink",
        "parent_symlink",
        "fifo",
        "wrong_project_key",
        "wrong_artifact_key",
        "invalid_json",
        "invalid_storyboard",
    ],
)
def test_unavailable_objects_are_safe(
    ai_client, database, storage, job, published, tmp_path, fault
):
    artifact = published["storyboard" if fault.startswith("invalid_") else "video"]
    path = storage.root / artifact.storage_key
    if fault in {"missing", "symlink", "fifo"}:
        path.unlink()
        if fault == "symlink":
            private = tmp_path / "private"
            private.write_bytes(b"private-key")
            path.symlink_to(private)
        elif fault == "fifo":
            os.mkfifo(path)
    elif fault == "parent_symlink":
        moved = tmp_path / "moved"
        path.parent.rename(moved)
        path.parent.symlink_to(moved, target_is_directory=True)
    elif fault in {"truncated", "checksum"}:
        data = path.read_bytes()
        path.write_bytes(data[:-1] if fault == "truncated" else b"X" + data[1:])
    elif fault.startswith("wrong_"):
        key = storage.storage_key(
            uuid4() if fault == "wrong_project_key" else job.project_id, uuid4()
        )
        with database.engine.begin() as connection:
            connection.execute(
                update(AIJobArtifact)
                .where(AIJobArtifact.id == artifact.id)
                .values(storage_key=key)
            )
    else:
        data = b"{broken" if fault == "invalid_json" else b'{"cuts": "private-key"}'
        path.write_bytes(data)
        with database.engine.begin() as connection:
            connection.execute(
                update(AIJobArtifact)
                .where(AIJobArtifact.id == artifact.id)
                .values(size_bytes=len(data), sha256=hashlib.sha256(data).hexdigest())
            )
    response = ai_client.get(job_url(job) + f"/artifacts/{artifact.id}")
    assert response.status_code == 503
    assert response.json() == {
        "code": "artifact_unavailable",
        "message": "The artifact is currently unavailable.",
    }
    assert response.headers["x-content-type-options"] == "nosniff"
    assert "private-key" not in response.text
    assert str(tmp_path) not in response.text


def test_post_validated_upload_is_not_queued(ai_client, database, clip_bytes):
    project = database.create_project("Upload inference gate")
    upload = ai_client.post(
        f"/projects/{project.id}/media",
        files={"files": ("my-upload.mp4", clip_bytes, "video/mp4")},
    )
    assert upload.status_code == 201, upload.text
    body = {
        "kind": "first_cut",
        "intent": "A short story",
        "target_seconds": 10,
        "media_ids": [upload.json()["items"][0]["id"]],
    }
    response = ai_client.post(f"/projects/{project.id}/ai-jobs", json=body)
    assert response.status_code == 503
    assert response.json()["code"] == "upload_inference_unavailable"
    with database._sessions() as session:
        assert session.scalar(select(func.count()).select_from(AIJob)) == 0
    other = database.create_project("Other")
    assert ai_client.post(f"/projects/{other.id}/ai-jobs", json=body).status_code == 404
    body["media_ids"] = [str(uuid4())]
    assert (
        ai_client.post(f"/projects/{project.id}/ai-jobs", json=body).status_code == 404
    )
    assert ai_client.post(f"/projects/{uuid4()}/ai-jobs", json=body).status_code == 404


@pytest.mark.parametrize(
    "change",
    [
        {"intent": "  "},
        {"intent": "x" * 1001},
        {"target_seconds": 0},
        {"target_seconds": 121},
        {"target_seconds": -1},
        {"target_seconds": True},
        {"target_seconds": "NaN"},
        {"target_seconds": "Infinity"},
        {"media_ids": []},
        {"media_ids": ["../private"]},
        {"media_ids": [str(uuid4()) for _ in range(11)]},
        {"media_ids": ["00000000-0000-0000-0000-000000000001"] * 2},
        {"kind": "arbitrary"},
        {"evidence_directory": "/private"},
        {"lease_token": str(uuid4())},
    ],
)
def test_invalid_creation(ai_client, database, change):
    project = database.create_project("Validation")
    body = {
        "kind": "first_cut",
        "intent": "A short story",
        "target_seconds": 10,
        "media_ids": [str(uuid4())],
        **change,
    }
    response = ai_client.post(f"/projects/{project.id}/ai-jobs", json=body)
    assert response.status_code == 422, response.text
    assert response.json() == {
        "code": "invalid_request",
        "message": "Request fields are invalid.",
    }
    assert database.claim_next_ai_job() is None
