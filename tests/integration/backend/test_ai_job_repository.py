
from uuid import uuid4

import pytest

from intentcut.backend.ai_jobs import AIJobStatus
from intentcut.backend.database import ProjectNotFound


def test_create_and_retrieve_ai_job(database):
    project = database.create_project("AI Job Test")

    payload = {
        "kind": "first_cut",
        "media_ids": [],
        "intent": "Create a coding workspace video",
        "target_seconds": 10,
    }

    job = database.create_ai_job(project.id, payload)

    assert job.id is not None
    assert job.project_id == project.id
    assert job.status == AIJobStatus.QUEUED.value

    retrieved = database.get_ai_job(project.id, job.id)

    assert retrieved is not None
    assert retrieved.id == job.id
    assert retrieved.request_payload == payload

    # A job must not be visible through another project.
    other_project = database.create_project("Other Project")

    assert database.get_ai_job(other_project.id, job.id) is None


def test_reject_job_for_missing_project(database):
    with pytest.raises(ProjectNotFound):
        database.create_ai_job(
            uuid4(),
            {"kind": "first_cut"},
        )


def test_claim_job_only_once(database):
    project = database.create_project("Worker Claim Test")

    original = database.create_ai_job(
        project.id,
        {"kind": "first_cut"},
    )

    claimed = database.claim_next_ai_job()

    assert claimed is not None
    assert claimed.id == original.id
    assert claimed.status == AIJobStatus.RUNNING.value
    assert claimed.started_at is not None

    # The same running job must not be claimed again.
    second_claim = database.claim_next_ai_job()

    assert second_claim is None

    persisted = database.get_ai_job(project.id, original.id)

    assert persisted is not None
    assert persisted.status == AIJobStatus.RUNNING.value


def test_complete_ai_job(database):
    project = database.create_project("Completion Test")

    job = database.create_ai_job(
        project.id,
        {"kind": "first_cut"},
    )

    # A queued job cannot complete without being claimed.
    assert database.complete_ai_job(project.id, job.id) is False

    claimed = database.claim_next_ai_job()
    assert claimed is not None
    assert claimed.id == job.id

    assert database.complete_ai_job(project.id, job.id) is True

    persisted = database.get_ai_job(project.id, job.id)

    assert persisted is not None
    assert persisted.status == AIJobStatus.SUCCEEDED.value
    assert persisted.finished_at is not None
    assert persisted.error_code is None

    # Terminal jobs cannot be completed twice.
    assert database.complete_ai_job(project.id, job.id) is False

    # A successful job cannot later become failed.
    assert (
        database.fail_ai_job(
            project.id, job.id, "render_failed"
        )
        is False
    )


def test_fail_ai_job(database):
    project = database.create_project("Failure Test")

    job = database.create_ai_job(
        project.id,
        {"kind": "first_cut"},
    )

    claimed = database.claim_next_ai_job()
    assert claimed is not None
    assert claimed.id == job.id

    assert (
        database.fail_ai_job(
            project.id, job.id, "inference_failed"
        )
        is True
    )

    persisted = database.get_ai_job(project.id, job.id)

    assert persisted is not None
    assert persisted.status == AIJobStatus.FAILED.value
    assert persisted.error_code == "inference_failed"
    assert persisted.finished_at is not None

    # Failed jobs cannot be completed accidentally.
    assert database.complete_ai_job(project.id, job.id) is False


def test_completion_is_project_scoped(database):
    owner = database.create_project("Owner")
    other = database.create_project("Other")

    job = database.create_ai_job(
        owner.id,
        {"kind": "first_cut"},
    )

    database.claim_next_ai_job()

    assert database.complete_ai_job(other.id, job.id) is False

    persisted = database.get_ai_job(owner.id, job.id)
    assert persisted is not None
    assert persisted.status == AIJobStatus.RUNNING.value


def test_reject_invalid_error_code(database):
    project = database.create_project("Error Code Test")

    job = database.create_ai_job(
        project.id,
        {"kind": "first_cut"},
    )

    database.claim_next_ai_job()

    with pytest.raises(ValueError, match="Invalid AI job error code"):
        database.fail_ai_job(
            project.id,
            job.id,
            "Secret token: abc123",
        )
