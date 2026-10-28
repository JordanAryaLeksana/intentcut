"""Acceptance: real uploads, PostgreSQL, windows, FFmpeg, publication and downloads."""

import hashlib
import json
import subprocess
from datetime import timedelta
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr
from sqlalchemy import func, select, update

from intentcut.backend.ai_artifacts import AIArtifactPublisher
from intentcut.backend.ai_processing_adapter import RealAIProcessingAdapter
from intentcut.backend.ai_worker import AIJobWorker
from intentcut.backend.app import create_app
from intentcut.backend.database.database_models import AIJob
from intentcut.media.probe_parser import MediaProbe
from intentcut.media.render import OutputValidator

pytestmark = [pytest.mark.integration, pytest.mark.postgres]


@pytest.fixture
def processing_settings(settings):
    return settings.model_copy(
        update={
            "ai_jobs_local_enabled": True,
            "ai_processing_enabled": True,
            "model_api_key": SecretStr("fake-provider-test-only"),
        }
    )


@pytest.fixture
def api(processing_settings, database, storage):
    app = create_app(processing_settings, database=database, storage=storage)
    with TestClient(
        app, base_url="http://127.0.0.1:8000", client=("127.0.0.1", 12345)
    ) as client:
        yield client


@pytest.fixture
def uploaded(api, clip_bytes, artifact_video_bytes):
    project = api.post("/projects", json={"name": "Uploaded footage"}).json()["id"]
    response = api.post(
        f"/projects/{project}/media",
        files=[
            ("files", ("same-name.mp4", clip_bytes, "video/mp4")),
            ("files", ("same-name.mp4", artifact_video_bytes, "video/mp4")),
        ],
    )
    assert response.status_code == 201, response.text
    return project, [item["id"] for item in response.json()["items"]]


def submit(api, uploaded, **changes):
    project, media = uploaded
    return api.post(
        f"/projects/{project}/ai-jobs",
        json={
            "kind": "first_cut",
            "intent": "Show blue, then red",
            "target_seconds": 1.0,
            "media_ids": media,
            **changes,
        },
    )


def worker(database, storage, settings, muse):
    return AIJobWorker(
        database,
        RealAIProcessingAdapter(
            database=database, storage=storage, settings=settings, muse=muse
        ),
        artifact_publisher=AIArtifactPublisher(storage),
    )


def assert_color(path, seconds, color):
    # Sample the center so the renderer's black letterboxing does not affect this.
    result = subprocess.run(
        [
            "ffmpeg",
            "-v",
            "error",
            "-ss",
            str(seconds),
            "-i",
            str(path),
            "-vf",
            "crop=20:20:350:630,scale=1:1",
            "-frames:v",
            "1",
            "-f",
            "rawvideo",
            "-pix_fmt",
            "rgb24",
            "-",
        ],
        check=True,
        capture_output=True,
        timeout=30,
    )
    red, green, blue = result.stdout
    assert green < 50
    if color == "blue":
        assert blue > 180 and red < 50
    else:
        assert red > 180 and blue < 50


@pytest.mark.parametrize("count", [1, 2])
def test_upload_to_download_real_mp4(
    api,
    uploaded,
    database,
    storage,
    processing_settings,
    fake_muse,
    tmp_path,
    count,
    clip_bytes,
    artifact_video_bytes,
):
    project, media = uploaded
    media = media[:count]
    response = submit(api, (project, media))
    assert response.status_code == 202, response.text
    accepted = response.json()
    assert set(accepted) == {"id", "status", "status_url"}
    assert accepted["status"] == "queued"
    assert response.headers["location"] == accepted["status_url"]
    job_id = UUID(accepted["id"])
    queued = database.get_ai_job(UUID(project), job_id)
    assert queued.status == "queued" and queued.attempt_count == 0
    assert queued.request_payload["media_ids"] == media
    assert queued.request_payload["source_sha256"] == {
        mid: hashlib.sha256(data).hexdigest()
        for mid, data in zip(media, [clip_bytes, artifact_video_bytes], strict=False)
    }
    assert not fake_muse.analyzed  # HTTP did not run inference.
    assert worker(database, storage, processing_settings, fake_muse).process_one(
        job_id=job_id
    )
    status = api.get(accepted["status_url"]).json()
    assert status["status"] == "succeeded", status
    assert status["attempt_count"] == 1 and status["finished_at"]
    assert len(fake_muse.analyzed) == count
    assert len(fake_muse.selections) == 1
    assert [item["media_id"] for item in fake_muse.selections[0]] == media
    assert len({p.parent for p in fake_muse.analyzed}) == count
    assert "clip_b" not in json.dumps(fake_muse.selections)
    assert all(str(storage.root) not in json.dumps(e) for e in fake_muse.selections)
    items = api.get(accepted["status_url"] + "/artifacts").json()["items"]
    assert {item["kind"] for item in items} == {"storyboard", "video"}
    downloads = {item["kind"]: api.get(item["download_url"]) for item in items}
    assert all(r.status_code == 200 for r in downloads.values())
    storyboard = downloads["storyboard"].json()
    assert [cut["media_id"] for cut in storyboard["cuts"]] == list(reversed(media))
    assert [cut["playback_order"] for cut in storyboard["cuts"]] == list(range(count))
    assert all(
        c["start_seconds"] == 0 and c["end_seconds"] == 0.25 for c in storyboard["cuts"]
    )
    assert "editorial_reason" not in downloads["storyboard"].text
    assert str(storage.root) not in downloads["storyboard"].text
    assert downloads["video"].headers["content-type"] == "video/mp4"
    video = tmp_path / "downloaded.mp4"
    video.write_bytes(downloads["video"].content)
    metadata = MediaProbe().probe(video)
    OutputValidator().validate(metadata, storyboard["render_seconds"])
    OutputValidator().verify_playback(video, metadata.duration)
    assert_color(video, 0.1, "blue" if count == 2 else "red")
    if count == 2:
        assert_color(video, 0.4, "red")
    assert metadata.duration <= 1.0
    for artifact in database.list_ai_job_artifacts(UUID(project), job_id):
        assert (
            hashlib.sha256(
                (storage.root / artifact.storage_key).read_bytes()
            ).hexdigest()
            == artifact.sha256
        )


@pytest.mark.parametrize(
    "problem", ["missing", "cross_project", "duplicate", "malformed"]
)
def test_reject_media_references(api, uploaded, database, problem):
    project, media = uploaded
    if problem == "cross_project":
        project = api.post("/projects", json={"name": "Other"}).json()["id"]
    elif problem == "missing":
        media = [str(uuid4())]
    elif problem == "duplicate":
        media = [media[0], media[0]]
    else:
        media = ["../private.mp4"]
    response = submit(api, (project, media))
    assert response.status_code == (
        404 if problem in {"missing", "cross_project"} else 422
    )
    assert database.claim_next_ai_job() is None


@pytest.mark.parametrize(
    "fault", ["missing", "symlink", "truncated", "changed_after_submit"]
)
def test_invalid_source_never_calls_muse(
    api, uploaded, database, storage, processing_settings, fake_muse, tmp_path, fault
):
    project, media = uploaded
    asset = database.get_media(UUID(project), UUID(media[0]))
    path = storage.root / asset.storage_key
    if fault == "changed_after_submit":
        response = submit(api, uploaded)
        assert response.status_code == 202
        data = path.read_bytes()
        path.write_bytes(data[:-1] + bytes([data[-1] ^ 1]))
        assert worker(database, storage, processing_settings, fake_muse).process_one()
        status = api.get(response.json()["status_url"]).json()
        assert status["status"] == "failed"
        assert status["error_code"] == "source_unavailable"
    else:
        path.unlink()
        if fault == "symlink":
            path.symlink_to(tmp_path / "private")
        elif fault == "truncated":
            path.write_bytes(b"x")
        response = submit(api, uploaded)
        assert response.status_code == 422
        assert response.json()["code"] == "source_unavailable"
        assert database.claim_next_ai_job() is None
    assert not fake_muse.analyzed


@pytest.mark.parametrize(
    "change",
    [
        {"ai_processing_enabled": False},
        {"model_api_key": None},
        {"model_api_key": SecretStr(" ")},
    ],
)
def test_unconfigured_post_does_not_queue(
    processing_settings, database, storage, uploaded, change
):
    settings = processing_settings.model_copy(update=change)
    app = create_app(settings, database=database, storage=storage)
    with TestClient(
        app, base_url="http://127.0.0.1", client=("127.0.0.1", 1)
    ) as client:
        response = submit(client, uploaded)
    assert response.status_code == 503
    assert response.json()["code"] == "upload_inference_unavailable"
    assert database.claim_next_ai_job() is None


@pytest.mark.parametrize(
    "limit", ["ai_max_media", "ai_max_windows", "ai_max_source_bytes"]
)
def test_admission_budgets(processing_settings, database, storage, uploaded, limit):
    settings = processing_settings.model_copy(update={limit: 1})
    with TestClient(
        create_app(settings, database=database, storage=storage),
        base_url="http://127.0.0.1",
        client=("127.0.0.1", 1),
    ) as client:
        response = submit(client, uploaded)
    assert response.status_code == 422
    assert response.json()["code"] == "processing_limit"
    assert database.claim_next_ai_job() is None


@pytest.mark.parametrize(
    "limit",
    [
        "ai_max_remote_file_bytes",
        "ai_max_remote_total_bytes",
        "ai_max_inference_requests",
    ],
)
def test_worker_budgets_before_paid_calls(
    api, uploaded, database, storage, processing_settings, fake_muse, limit
):
    response = submit(api, uploaded)
    settings = processing_settings.model_copy(update={limit: 1})
    assert worker(database, storage, settings, fake_muse).process_one()
    status = api.get(response.json()["status_url"]).json()
    assert status["status"] == "failed" and status["error_code"] == "processing_limit"
    assert not fake_muse.analyzed and not fake_muse.selections
    assert api.get(response.json()["status_url"] + "/artifacts").json() == {"items": []}


@pytest.mark.parametrize("bad_selection", ["unknown", "duplicate", "overflow"])
def test_invalid_selection_cannot_publish(
    api, uploaded, database, storage, processing_settings, fake_muse, bad_selection
):
    response = submit(
        api, uploaded, target_seconds=0.4 if bad_selection == "overflow" else 1
    )
    fake_muse.selection_indices = (
        [99]
        if bad_selection == "unknown"
        else ([0, 0] if bad_selection == "duplicate" else [0, 1])
    )
    assert worker(database, storage, processing_settings, fake_muse).process_one()
    status = api.get(response.json()["status_url"]).json()
    assert status["status"] == "failed"
    assert status["error_code"] == "invalid_ai_selection"
    assert api.get(response.json()["status_url"] + "/artifacts").json() == {"items": []}
    assert not list((storage.root / ".jobs").rglob("first_cut.mp4"))


def test_stale_attempt_reuses_only_grounded_cache(
    api, uploaded, database, storage, processing_settings, fake_muse
):
    response = submit(api, uploaded)
    job_id = UUID(response.json()["id"])

    def expire():
        with database.engine.begin() as connection:
            connection.execute(
                update(AIJob)
                .where(AIJob.id == job_id)
                .values(lease_expires_at=func.clock_timestamp() - timedelta(seconds=1))
            )

    fake_muse.on_select = expire
    assert worker(database, storage, processing_settings, fake_muse).process_one()
    assert api.get(response.json()["status_url"] + "/artifacts").json() == {"items": []}
    assert len(fake_muse.analyzed) == 2
    recovered = database.recover_expired_ai_job(max_attempts=2, job_id=job_id)
    assert recovered.status == "queued"
    fake_muse.on_select = None
    assert worker(database, storage, processing_settings, fake_muse).process_one()
    status = api.get(response.json()["status_url"]).json()
    assert status["status"] == "succeeded" and status["attempt_count"] == 2
    assert len(fake_muse.analyzed) == 2  # Exact-window cache reused across attempts.
    assert len(fake_muse.selections) == 2
    assert len(list((storage.root / ".jobs" / str(job_id)).glob("attempt_*"))) == 2


def test_targeted_worker_leaves_other_jobs_queued(
    api, uploaded, database, storage, processing_settings, fake_muse
):
    first = submit(api, uploaded).json()
    second = submit(api, uploaded).json()
    assert worker(database, storage, processing_settings, fake_muse).process_one(
        job_id=UUID(second["id"])
    )
    assert api.get(first["status_url"]).json()["status"] == "queued"
    assert api.get(second["status_url"]).json()["status"] == "succeeded"
    with database._sessions() as session:
        assert session.scalar(select(func.count()).select_from(AIJob)) == 2


def test_worker_entry_point_uses_real_pipeline_without_paid_calls(
    api, uploaded, database, storage, processing_settings, fake_muse, monkeypatch
):
    from unittest.mock import MagicMock

    from intentcut.backend import worker_cli

    accepted = submit(api, uploaded).json()
    client = MagicMock()
    factory = MagicMock(return_value=client)
    monkeypatch.setattr(worker_cli, "OpenAI", factory)
    monkeypatch.setattr(worker_cli, "MuseClient", lambda _: fake_muse)
    monkeypatch.setattr(worker_cli.Database, "connect", lambda _: database)
    assert worker_cli.run_worker(processing_settings, job_id=UUID(accepted["id"])) == 1
    assert api.get(accepted["status_url"]).json()["status"] == "succeeded"
    assert factory.call_args.kwargs["max_retries"] == 0
    assert factory.call_args.kwargs["timeout"] == 180.0
    client.__exit__.assert_called_once()


def test_long_video_budget_before_provider_calls(api, uploaded, database):
    from intentcut.backend.database.database_models import MediaAsset

    project, media = uploaded
    with database.engine.begin() as connection:
        connection.execute(
            update(MediaAsset)
            .where(MediaAsset.id == UUID(media[0]))
            .values(duration_seconds=3600)
        )
    response = submit(api, uploaded, target_seconds=120)
    assert response.status_code == 422
    assert response.json()["code"] == "processing_limit"
    assert database.claim_next_ai_job() is None


def test_provider_failure_is_safe(
    api, uploaded, database, storage, processing_settings, fake_muse, monkeypatch
):
    def fail(_):
        raise RuntimeError("private-provider-secret /internal/workspace")

    monkeypatch.setattr(fake_muse, "analyze", fail)
    accepted = submit(api, uploaded).json()
    assert worker(database, storage, processing_settings, fake_muse).process_one()
    response = api.get(accepted["status_url"])
    assert response.json()["status"] == "failed"
    assert response.json()["error_code"] == "provider_unavailable"
    assert "private-provider" not in response.text
    assert "workspace" not in response.text
    assert api.get(accepted["status_url"] + "/artifacts").json() == {"items": []}


def test_manual_smoke_orchestration_with_fake_muse(
    api,
    database,
    storage,
    processing_settings,
    fake_muse,
    tmp_path,
    clip_bytes,
    artifact_video_bytes,
    monkeypatch,
    capsys,
):
    """Exercise the exact manual workflow while replacing its provider boundary."""
    import importlib.util
    from contextlib import contextmanager
    from pathlib import Path

    script = Path(__file__).resolve().parents[3] / "scripts" / "smoke_uploaded_job.py"
    spec = importlib.util.spec_from_file_location("smoke_uploaded_job", script)
    smoke = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(smoke)
    red, blue = tmp_path / "red.mp4", tmp_path / "blue.mp4"
    red.write_bytes(clip_bytes)
    blue.write_bytes(artifact_video_bytes)

    @contextmanager
    def http_client(**kwargs):
        assert kwargs["trust_env"] is False
        yield api

    def run_fake(settings, *, job_id):
        return int(
            worker(database, storage, settings, fake_muse).process_one(job_id=job_id)
        )

    monkeypatch.setattr(smoke.httpx, "Client", http_client)
    monkeypatch.setattr(smoke, "BackendSettings", lambda: processing_settings)
    monkeypatch.setattr(smoke, "run_worker", run_fake)
    monkeypatch.setattr(
        "sys.argv",
        [str(script), "--live", str(red), str(blue), "--target-seconds", "1"],
    )
    monkeypatch.chdir(tmp_path)
    assert smoke.main() == 0
    output = capsys.readouterr().out
    assert "PASS:" in output and "fully decoded" in output
    assert "fake-provider-test-only" not in output
    assert len(list((tmp_path / ".local" / "smoke").glob("*/video.mp4"))) == 1
