"""Persistent progress and fencing against real PostgreSQL, without AI calls."""

import json
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from pathlib import Path
from threading import Event
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select, update

from intentcut.backend.app import create_app
from intentcut.backend.storage.database import Database
from intentcut.backend.storage.database_models import AIJob

pytestmark = [pytest.mark.integration, pytest.mark.postgres]


def claim(database):
    project = database.create_project("Progress test")
    job = database.create_ai_job(project.id, {"kind": "first_cut"})
    return database.claim_next_ai_job(job_id=job.id)


def expire(database, job):
    with database.engine.begin() as connection:
        connection.execute(
            update(AIJob)
            .where(AIJob.id == job.id)
            .values(lease_expires_at=func.clock_timestamp() - timedelta(seconds=1))
        )


def report(database, job, stage="understanding_footage", **kwargs):
    if stage == "understanding_footage":
        kwargs = {"completed_windows": 0, "total_windows": 2, **kwargs}
    return database.update_ai_job_progress(
        job.project_id, job.id, job.lease_token, stage, **kwargs
    )


def test_progress_survives_new_database_instance_and_heartbeat(database):
    job = claim(database)
    assert report(database, job)
    first = Database(database.engine).get_ai_job(job.project_id, job.id)
    assert first.progress["completed_windows"] == 0
    started = first.progress["stage_started_at"]
    assert report(database, job, completed_windows=1)
    current = database.get_ai_job(job.project_id, job.id)
    assert current.progress["stage_started_at"] == started
    assert current.progress["updated_at"] >= first.progress["updated_at"]
    assert database.heartbeat_ai_job(job.project_id, job.id, job.lease_token)
    assert database.get_ai_job(job.project_id, job.id).progress == current.progress
    assert report(database, job, "selecting_story")
    changed = database.get_ai_job(job.project_id, job.id).progress
    assert changed["stage_started_at"] >= current.progress["updated_at"]
    assert "completed_windows" not in changed


def test_progress_is_fenced_by_project_token_status_and_expiry(database):
    job = claim(database)
    assert report(database, job)
    for project, token in [(uuid4(), job.lease_token), (job.project_id, uuid4())]:
        assert not database.update_ai_job_progress(
            project, job.id, token, "rendering_video"
        )
    assert (
        database.get_ai_job(job.project_id, job.id).progress["stage"]
        == "understanding_footage"
    )
    expire(database, job)
    assert not report(database, job, completed_windows=1)
    assert database.get_ai_job(job.project_id, job.id).has_active_lease is False


@pytest.mark.parametrize("terminal", ["complete", "fail"])
def test_terminal_transition_clears_progress_and_rejects_further_writes(
    database, terminal
):
    job = claim(database)
    assert report(database, job)
    if terminal == "complete":
        assert database.complete_ai_job(job.project_id, job.id, job.lease_token)
    else:
        assert database.fail_ai_job(
            job.project_id, job.id, job.lease_token, "processing_failed"
        )
    current = database.get_ai_job(job.project_id, job.id)
    assert current.progress is None
    assert not report(database, job, "publishing_artifacts")


@pytest.mark.parametrize("attempts", [1, 2])
def test_recovery_clears_progress_and_new_attempt_cannot_use_old_token(
    database, attempts
):
    job = claim(database)
    assert report(database, job, completed_windows=1)
    expire(database, job)
    recovered = database.recover_expired_ai_job(job_id=job.id, max_attempts=attempts)
    assert recovered.progress is None
    assert recovered.status == ("failed" if attempts == 1 else "queued")
    assert not report(database, job, completed_windows=2)
    if attempts == 2:
        second = database.claim_next_ai_job(job_id=job.id)
        assert second.attempt_count == 2 and second.progress is None
        assert second.lease_token != job.lease_token
        assert report(database, second, "preparing_media")
        assert not report(database, job, "rendering_video")
        assert (
            database.get_ai_job(job.project_id, job.id).progress["stage"]
            == "preparing_media"
        )


def test_progress_cannot_regress_within_attempt(database):
    job = claim(database)
    assert report(database, job, completed_windows=1)
    for stage, changes in [
        ("preparing_media", {}),
        ("understanding_footage", {"completed_windows": 0}),
        ("understanding_footage", {"completed_windows": 1, "total_windows": 3}),
    ]:
        with pytest.raises(ValueError, match="backwards"):
            report(database, job, stage, **changes)
    assert (
        database.get_ai_job(job.project_id, job.id).progress["completed_windows"] == 1
    )


def test_waiting_progress_writer_rechecks_expiry_after_row_lock(database):
    job = claim(database)
    assert report(database, job)
    entered = Event()
    with ThreadPoolExecutor(max_workers=1) as pool:
        with database._sessions.begin() as session:
            session.scalar(select(AIJob).where(AIJob.id == job.id).with_for_update())

            def blocked_writer():
                entered.set()
                return report(database, job, completed_windows=1)

            future = pool.submit(blocked_writer)
            assert entered.wait(timeout=5)
            session.execute(
                update(AIJob)
                .where(AIJob.id == job.id)
                .values(lease_expires_at=func.clock_timestamp() - timedelta(seconds=1))
            )
        assert future.result(timeout=10) is False
    assert (
        database.get_ai_job(job.project_id, job.id).progress["completed_windows"] == 0
    )


def test_api_progress_is_additive_safe_and_hidden_for_expired_or_terminal_jobs(
    database, storage, settings, tmp_path
):
    configured = settings.model_copy(update={"ai_jobs_local_enabled": True})
    project = database.create_project("API progress")
    queued = database.create_ai_job(
        project.id, {"kind": "first_cut", "private": "secret"}
    )
    app = create_app(configured, database=database, storage=storage)
    with TestClient(
        app, base_url="http://127.0.0.1:8000", client=("127.0.0.1", 12345)
    ) as api:
        url = f"/projects/{project.id}/ai-jobs/{queued.id}"
        assert api.get(url).json()["progress"] is None
        job = database.claim_next_ai_job(job_id=queued.id)
        assert api.get(url).json()["progress"] is None  # Claimed, no actual stage yet.
        assert report(database, job, completed_windows=1)
        body = api.get(url).json()
        assert body["status"] == "running" and body["attempt_count"] == 1
        assert set(body["progress"]) == {
            "stage",
            "stage_started_at",
            "updated_at",
            "completed_windows",
            "total_windows",
        }
        assert body["progress"]["completed_windows"] == 1
        (tmp_path / "progress-response.json").write_text(json.dumps(body, indent=2))
        assert "secret" not in str(body) and "lease_token" not in body
        expire(database, job)
        assert api.get(url).json()["status"] == "running"
        assert api.get(url).json()["progress"] is None
        database.recover_expired_ai_job(job_id=job.id, max_attempts=2)
        assert api.get(url).json()["status"] == "queued"
        assert api.get(url).json()["progress"] is None
        second = database.claim_next_ai_job(job_id=job.id)
        assert report(database, second, "preparing_media")
        database.fail_ai_job(
            job.project_id, job.id, second.lease_token, "processing_failed"
        )
        assert api.get(url).json()["progress"] is None


def test_existing_database_migration_is_additive_and_idempotent(database):
    job = claim(database)
    migration = Path("scripts/migrations/001_ai_job_progress.sql").read_text()
    with database.engine.begin() as connection:
        connection.exec_driver_sql("ALTER TABLE ai_jobs DROP COLUMN progress")
        connection.exec_driver_sql(migration)
        connection.exec_driver_sql(migration)
    current = database.get_ai_job(job.project_id, job.id)
    assert current.request_payload == {"kind": "first_cut"}
    assert current.progress is None
    assert report(database, current, "preparing_media")
