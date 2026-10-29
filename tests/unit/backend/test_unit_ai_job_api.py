"""Local security gate and hostile storage metadata without provider calls."""

import hashlib
from datetime import UTC, datetime
from io import BytesIO
from uuid import uuid4

import anyio
import pytest
from fastapi.testclient import TestClient
from sqlalchemy.exc import OperationalError

from intentcut.backend.ai_job_routes import SnapshotResponse
from intentcut.backend.ai_job_service import AIJobService
from intentcut.backend.app import create_app
from intentcut.backend.storage.database_models import AIJob, AIJobArtifact


@pytest.fixture
def job(database, project):
    now = datetime.now(UTC)
    job = AIJob(
        id=uuid4(),
        project_id=project.id,
        status="running",
        created_at=now,
        updated_at=now,
        started_at=now,
        finished_at=None,
        attempt_count=1,
        error_code=None,
        request_payload={"secret": "/private"},
        lease_token=uuid4(),
    )
    database.get_ai_job.return_value = job
    database.list_ai_job_artifacts.return_value = []
    return job


def url(job):
    return f"/projects/{job.project_id}/ai-jobs/{job.id}"


def local_app(settings, database, storage, enabled=True):
    return create_app(
        settings.model_copy(update={"ai_jobs_local_enabled": enabled}),
        database=database,
        storage=storage,
    )


@pytest.mark.parametrize(
    "method,suffix",
    [
        ("get", ""),
        ("get", "/artifacts"),
        ("get", f"/artifacts/{uuid4()}"),
        ("post", None),
    ],
)
def test_disabled_by_default(settings, database, storage, job, method, suffix):
    app = create_app(settings, database=database, storage=storage)
    with TestClient(
        app, base_url="http://127.0.0.1", client=("127.0.0.1", 1)
    ) as client:
        path = url(job) + suffix if suffix is not None else url(job).rsplit("/", 1)[0]
        response = getattr(client, method)(path)
    assert response.status_code == 503
    assert response.json()["code"] == "ai_api_unavailable"
    assert response.headers["cache-control"] == "private, no-store"
    database.get_ai_job.assert_not_called()
    database.create_ai_job.assert_not_called()


@pytest.mark.parametrize(
    "peer,host,headers",
    [
        ("192.0.2.1", "127.0.0.1", {}),
        ("testclient", "127.0.0.1", {}),
        ("127.0.0.1", "public.example", {}),
        ("127.0.0.1", "127.0.0.1.evil.example", {}),
        ("127.0.0.1", "127.0.0.1", {"origin": "https://evil.example"}),
        ("127.0.0.1", "127.0.0.1", {"origin": "http://127.0.0.1"}),
        ("127.0.0.1", "127.0.0.1", {"sec-fetch-site": "cross-site"}),
        ("127.0.0.1", "127.0.0.1", {"x-forwarded-for": "127.0.0.1"}),
        ("127.0.0.1", "127.0.0.1", {"x-forwarded-proto": "https"}),
        ("127.0.0.1", "127.0.0.1", {"forwarded": "for=127.0.0.1"}),
        ("127.0.0.1", "127.0.0.1", {"via": "proxy"}),
    ],
)
def test_reject_remote_browser_and_proxy_access(
    settings, database, storage, job, peer, host, headers
):
    app = local_app(settings, database, storage)
    with TestClient(app, base_url=f"http://{host}", client=(peer, 1)) as client:
        for path in [url(job), url(job) + "/artifacts"]:
            response = client.get(path, headers=headers)
            assert response.status_code == 403
            assert response.json()["code"] == "local_access_required"
    database.get_ai_job.assert_not_called()


@pytest.mark.parametrize("peer,host", [("127.0.0.1", "localhost"), ("::1", "[::1]")])
def test_direct_loopback_access(settings, database, storage, job, peer, host):
    with TestClient(
        local_app(settings, database, storage),
        base_url=f"http://{host}",
        client=(peer, 1),
    ) as client:
        response = client.get(url(job))
    assert response.status_code == 200
    assert "lease" not in response.text and "private" not in response.text


@pytest.mark.parametrize(
    "key",
    [
        "../secret",
        "/etc/passwd",
        "projects/../../secret",
        "projects/%2e%2e/secret",
        "projects\\..\\secret",
    ],
)
def test_download_refuses_hostile_registered_key(settings, database, storage, job, key):
    artifact = AIJobArtifact(
        id=uuid4(),
        job_id=job.id,
        kind="video",
        size_bytes=10,
        sha256="a" * 64,
        storage_key=key,
    )
    database.list_ai_job_artifacts.return_value = [artifact]
    with TestClient(
        local_app(settings, database, storage),
        base_url="http://127.0.0.1",
        client=("127.0.0.1", 1),
    ) as client:
        response = client.get(url(job) + f"/artifacts/{artifact.id}")
        assert response.status_code == 503
        assert response.json()["code"] == "artifact_unavailable"
        assert key not in response.text
        assert client.get(url(job) + "/artifacts/not-a-uuid").status_code == 422


def test_database_failure_is_standardized(settings, database, storage, job):
    database.get_ai_job.side_effect = OperationalError(
        "secret SQL", {}, Exception("private credentials")
    )
    with TestClient(
        local_app(settings, database, storage),
        base_url="http://127.0.0.1",
        client=("127.0.0.1", 1),
    ) as client:
        response = client.get(url(job))
    assert response.status_code == 503
    assert response.json()["code"] == "database_unavailable"
    assert "private" not in response.text and "secret" not in response.text


def test_verified_snapshot_survives_file_replacement(database, storage, job):
    artifact_id = uuid4()
    original = b"\x00\x00\x00\x20ftyporiginal"
    with storage.staging() as batch:
        staged = storage.stage(BytesIO(original), batch, artifact_id)
        path = storage.publish(staged.path, job.project_id, artifact_id)
    artifact = AIJobArtifact(
        id=artifact_id,
        job_id=job.id,
        kind="video",
        size_bytes=len(original),
        sha256=hashlib.sha256(original).hexdigest(),
        storage_key=storage.storage_key(job.project_id, artifact_id),
    )
    with AIJobService(database, storage).snapshot(job.project_id, artifact) as snapshot:
        path.write_bytes(b"private-secret")
        assert snapshot.read() == original


def test_snapshot_closed_if_response_send_fails():
    snapshot = BytesIO(b"video")
    response = SnapshotResponse(snapshot, uuid4(), "video")

    async def receive():
        return {"type": "http.disconnect"}

    async def send(message):
        raise RuntimeError("disconnected")

    async def run():
        with pytest.raises(RuntimeError, match="disconnected"):
            await response(
                {"type": "http", "asgi": {"spec_version": "2.4"}}, receive, send
            )

    anyio.run(run)
    assert snapshot.closed
