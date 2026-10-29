"""Real PostgreSQL/FFmpeg manual renders; provider calls are fixture-only fakes."""

import hashlib
import subprocess
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr
from sqlalchemy import func, text, update

from intentcut.backend.ai_artifacts import AIArtifactPublisher
from intentcut.backend.ai_processing_adapter import RealAIProcessingAdapter
from intentcut.backend.ai_worker import AIJobWorker
from intentcut.backend.app import create_app
from intentcut.backend.editing.processor import ManualRenderProcessor
from intentcut.backend.storage.database_models import AIJob
from intentcut.media.frame_manifest import measured_frames
from intentcut.media.probe_parser import MediaProbe
from intentcut.media.render import OutputValidator

pytestmark = [pytest.mark.integration, pytest.mark.postgres]


@pytest.fixture
def setup(database, storage, settings, clip_bytes, artifact_video_bytes, fake_muse):
    settings = settings.model_copy(
        update={
            "ai_jobs_local_enabled": True,
            "ai_processing_enabled": True,
            "model_api_key": SecretStr("fake-only"),
        }
    )
    with TestClient(
        create_app(settings, database=database, storage=storage),
        base_url="http://127.0.0.1:8000",
        client=("127.0.0.1", 1234),
    ) as api:
        project = api.post("/projects", json={"name": "Manual render"}).json()["id"]
        media = api.post(
            f"/projects/{project}/media",
            files=[
                ("files", ("red.mp4", clip_bytes, "video/mp4")),
                ("files", ("blue.mp4", artifact_video_bytes, "video/mp4")),
            ],
        ).json()["items"]
        job = api.post(
            f"/projects/{project}/ai-jobs",
            json={
                "kind": "first_cut",
                "intent": "Colors",
                "target_seconds": 1,
                "media_ids": [m["id"] for m in media],
            },
        ).json()["id"]
        ai = AIJobWorker(
            database,
            RealAIProcessingAdapter(
                database=database, storage=storage, settings=settings, muse=fake_muse
            ),
            artifact_publisher=AIArtifactPublisher(storage),
        )
        ai.process_one(job_id=UUID(job))
        assert database.get_ai_job(UUID(project), UUID(job)).status == "succeeded"
        artifacts = api.get(f"/projects/{project}/ai-jobs/{job}/artifacts").json()[
            "items"
        ]
        storyboard = next(a for a in artifacts if a["kind"] == "storyboard")
        published = api.get(storyboard["download_url"]).json()
        body = {
            "expected_revision": 0,
            "base_job_id": job,
            "base_artifact_id": storyboard["id"],
            "window_indices": [c["window_index"] for c in published["cuts"]],
        }
        manual = AIJobWorker(
            database,
            ManualRenderProcessor(database, storage, settings),
            artifact_publisher=AIArtifactPublisher(storage),
        )
        yield api, project, body, manual, published


def test_save_validation_conflicts_isolation_and_migration(setup, database):
    api, project, body, _, _ = setup
    path = f"/projects/{project}/edit-draft"
    assert api.get(path).json()["draft"] is None
    saved = api.put(path, json=body)
    assert saved.status_code == 200, saved.text
    assert saved.json()["revision"] == 1
    assert api.get(path).json()["draft"] == saved.json()
    assert api.put(path, json=body).status_code == 409
    other = api.post("/projects", json={"name": "Other"}).json()["id"]
    assert api.put(f"/projects/{other}/edit-draft", json=body).status_code == 404
    for indices in [[999], [body["window_indices"][0]] * 2, [True], ["0"]]:
        assert (
            api.put(
                path, json={**body, "expected_revision": 1, "window_indices": indices}
            ).status_code
            == 422
        )
    assert (
        api.put(
            path, json={**body, "expected_revision": 1, "source_path": "/tmp/secret"}
        ).status_code
        == 422
    )
    assert (
        api.put(
            path,
            json={**body, "expected_revision": 1, "base_artifact_id": str(uuid4())},
        ).status_code
        == 404
    )
    migration = Path("scripts/migrations/002_edit_drafts.sql").read_text()
    with database.engine.begin() as connection:
        connection.execute(text(migration))
        connection.execute(text(migration))
    assert api.get(path).json()["draft"] == saved.json()

    # Concurrent updates with identical expected revision: exactly one wins.
    def save(_):
        return api.put(path, json={**body, "expected_revision": 1}).status_code

    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sorted(pool.map(save, range(2))) == [200, 409]
    empty = api.put(path, json={**body, "expected_revision": 2, "window_indices": []})
    assert empty.json()["revision"] == 3
    assert api.post(path + "/renders", json={"revision": 3}).status_code == 422


def sample(path, seconds):
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
    return list(result.stdout)


def test_exact_saved_revision_rerenders_real_reordered_and_removed_video(
    setup, database, tmp_path
):
    api, project, body, worker, published = setup
    path = f"/projects/{project}/edit-draft"
    original_items = api.get(
        f"/projects/{project}/ai-jobs/{body['base_job_id']}/artifacts"
    ).json()["items"]
    original_bytes = api.get(
        next(a["download_url"] for a in original_items if a["kind"] == "video")
    ).content
    # AI published blue/red; creator requests red/blue.
    reordered = list(reversed(body["window_indices"]))
    saved = api.put(path, json={**body, "window_indices": reordered}).json()
    admitted = api.post(path + "/renders", json={"revision": saved["revision"]})
    assert admitted.status_code == 202, admitted.text
    job = admitted.json()["id"]
    assert api.post(path + "/renders", json={"revision": 1}).json()["id"] == job
    # Mutate head after admission: job must render immutable revision 1 with both cuts.
    api.put(
        path, json={**body, "expected_revision": 1, "window_indices": reordered[:1]}
    )
    assert api.post(path + "/renders", json={"revision": 1}).status_code == 409
    worker.process_one(job_id=UUID(job), manual_only=True)
    status = api.get(f"/projects/{project}/ai-jobs/{job}").json()
    assert status["status"] == "succeeded", status
    items = api.get(f"/projects/{project}/ai-jobs/{job}/artifacts").json()["items"]
    video = api.get(
        next(a["download_url"] for a in items if a["kind"] == "video")
    ).content
    output = tmp_path / "reordered.mp4"
    output.write_bytes(video)
    story = api.get(
        next(a["download_url"] for a in items if a["kind"] == "storyboard")
    ).json()
    manifest = story["render_manifest"]
    assert [c["window_index"] for c in story["cuts"]] == reordered
    assert manifest["draft_revision"] == 1 and manifest["fps"] == 30
    assert manifest["total_frames"] == measured_frames(output) == 16
    assert [
        (c["output_start_frame"], c["output_end_frame"]) for c in manifest["cuts"]
    ] == [(0, 8), (8, 16)]
    assert abs(manifest["total_frames"] / 30 - story["total_seconds"]) > 0.001
    validator = OutputValidator()
    metadata = MediaProbe().probe(output)
    validator.validate(metadata, 16 / 30)
    validator.verify_playback(output, metadata.duration)
    red, _, blue = sample(output, 0.1)
    assert red > 180 and blue < 50
    red, _, blue = sample(output, 0.4)
    assert blue > 180 and red < 50
    assert (
        hashlib.sha256(original_bytes).hexdigest() != hashlib.sha256(video).hexdigest()
    )
    # Render revision 2 with the removed blue cut, keeping revision 1 artifacts.
    job2 = api.post(path + "/renders", json={"revision": 2}).json()["id"]
    worker.process_one(job_id=UUID(job2), manual_only=True)
    assert (
        api.get(f"/projects/{project}/ai-jobs/{job2}").json()["status"] == "succeeded"
    )
    assert len(api.get(path + "/renders").json()["items"]) == 2
    assert (
        api.get(next(a["download_url"] for a in items if a["kind"] == "video")).content
        == video
    )
    assert (
        api.get(
            next(a["download_url"] for a in original_items if a["kind"] == "video")
        ).content
        == original_bytes
    )


def test_manual_lease_recovery_and_no_ai_claim(setup, database):
    api, project, body, worker, _ = setup
    path = f"/projects/{project}/edit-draft"
    api.put(path, json=body)
    job = UUID(api.post(path + "/renders", json={"revision": 1}).json()["id"])
    unrelated = database.create_ai_job(
        UUID(project), {"pipeline_version": "uploaded_v1"}
    )
    old = database.claim_next_ai_job(job_id=job, manual_only=True)
    with database.engine.begin() as connection:
        connection.execute(
            update(AIJob)
            .where(AIJob.id == job)
            .values(lease_expires_at=func.clock_timestamp() - timedelta(seconds=1))
        )
    assert not database.update_ai_job_progress(
        UUID(project), job, old.lease_token, "rendering_video"
    )
    assert (
        database.recover_expired_ai_job(
            job_id=job, max_attempts=2, manual_only=True
        ).status
        == "queued"
    )
    worker.process_one(job_id=job, manual_only=True)
    assert database.get_ai_job(UUID(project), job).status == "succeeded"
    assert database.get_ai_job(UUID(project), job).attempt_count == 2
    assert database.get_ai_job(UUID(project), unrelated.id).status == "queued"
    assert database.claim_next_ai_job(job_id=unrelated.id, manual_only=True) is None
    assert not database.complete_ai_job(UUID(project), job, old.lease_token)


def test_changed_source_fails_without_artifacts(setup, database, storage):
    api, project, body, worker, _ = setup
    path = f"/projects/{project}/edit-draft"
    api.put(path, json=body)
    job = UUID(api.post(path + "/renders", json={"revision": 1}).json()["id"])
    with database._sessions() as session:
        payload = session.get(AIJob, job).request_payload
    media_id = UUID(payload["edit_plan"]["cuts"][0]["media_id"])
    asset = database.get_media(UUID(project), media_id)
    target = storage.root / asset.storage_key
    data = bytearray(target.read_bytes())
    data[-1] ^= 1
    target.write_bytes(data)
    worker.process_one(job_id=job, manual_only=True)
    assert database.get_ai_job(UUID(project), job).error_code == "source_unavailable"
    assert not database.list_ai_job_artifacts(UUID(project), job)


def test_migration_creates_table_idempotently_and_local_guard(
    database, storage, settings
):
    migration = Path("scripts/migrations/002_edit_drafts.sql").read_text()
    with database.engine.begin() as connection:
        connection.execute(text("DROP TABLE edit_drafts"))
        connection.execute(text("DROP INDEX uq_manual_render_revision"))
        connection.execute(text(migration))
        connection.execute(text(migration))
        assert connection.scalar(text("SELECT count(*) FROM edit_drafts")) == 0
    project = database.create_project("Guard")
    path = f"/projects/{project.id}/edit-draft"
    # Same opt-in loopback boundary as first-cut admission, including PUT.
    with TestClient(create_app(settings, database=database, storage=storage)) as api:
        assert api.get(path).status_code == 503
        assert api.put(path, json={}).status_code == 503
