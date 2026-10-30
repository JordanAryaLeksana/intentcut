
from uuid import uuid4

import pytest

from intentcut.backend.storage.database import ProjectNotFound
from intentcut.backend.jobs.domain import AIJobStatus


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
    job = database.create_ai_job(project.id, {"kind": "first_cut"})

    # A queued job cannot complete without ownership.
    assert database.complete_ai_job(
        project.id, job.id, uuid4()
    ) is False

    claimed = database.claim_next_ai_job()
    assert claimed is not None
    assert claimed.id == job.id
    assert claimed.lease_token is not None

    token = claimed.lease_token

    assert database.complete_ai_job(
        project.id, job.id, token
    ) is True

    persisted = database.get_ai_job(project.id, job.id)

    assert persisted is not None
    assert persisted.status == AIJobStatus.SUCCEEDED.value
    assert persisted.finished_at is not None
    assert persisted.error_code is None
    assert persisted.lease_token is None
    assert persisted.lease_expires_at is None

    # Terminal transitions cannot happen twice.
    assert database.complete_ai_job(
        project.id, job.id, token
    ) is False

    assert database.fail_ai_job(
        project.id, job.id, token, "render_failed"
    ) is False


def test_fail_ai_job(database):
    project = database.create_project("Failure Test")
    job = database.create_ai_job(project.id, {"kind": "first_cut"})

    claimed = database.claim_next_ai_job()
    assert claimed is not None
    assert claimed.id == job.id
    assert claimed.lease_token is not None

    token = claimed.lease_token

    assert database.fail_ai_job(
        project.id, job.id, token, "inference_failed"
    ) is True

    persisted = database.get_ai_job(project.id, job.id)

    assert persisted is not None
    assert persisted.status == AIJobStatus.FAILED.value
    assert persisted.error_code == "inference_failed"
    assert persisted.finished_at is not None
    assert persisted.lease_token is None
    assert persisted.lease_expires_at is None

    assert database.complete_ai_job(
        project.id, job.id, token
    ) is False


def test_completion_is_project_scoped(database):
    owner = database.create_project("Owner")
    other = database.create_project("Other")

    job = database.create_ai_job(
        owner.id,
        {"kind": "first_cut"},
    )

    claimed = database.claim_next_ai_job()
    assert claimed is not None
    assert claimed.id == job.id
    assert claimed.lease_token is not None

    assert database.complete_ai_job(
        other.id, job.id, claimed.lease_token
    ) is False

    persisted = database.get_ai_job(owner.id, job.id)

    assert persisted is not None
    assert persisted.status == AIJobStatus.RUNNING.value


def test_reject_invalid_error_code(database):
    project = database.create_project("Error Code Test")
    job = database.create_ai_job(project.id, {"kind": "first_cut"})

    claimed = database.claim_next_ai_job()
    assert claimed is not None
    assert claimed.id == job.id
    assert claimed.lease_token is not None

    with pytest.raises(
        ValueError, match="Invalid AI job error code"
    ):
        database.fail_ai_job(
            project.id,
            job.id,
            claimed.lease_token,
            "Secret token: abc123",
        )

def test_wrong_lease_token_cannot_finish_job(database):
    project = database.create_project("Fencing Test")
    job = database.create_ai_job(
        project.id,
        {"kind": "first_cut"},
    )

    claimed = database.claim_next_ai_job()
    assert claimed is not None
    assert claimed.lease_token is not None

    wrong_token = uuid4()

    assert database.complete_ai_job(
        project.id, job.id, wrong_token
    ) is False

    assert database.fail_ai_job(
        project.id, job.id, wrong_token, "render_failed"
    ) is False

    persisted = database.get_ai_job(project.id, job.id)
    assert persisted is not None
    assert persisted.status == AIJobStatus.RUNNING.value

    assert database.complete_ai_job(
        project.id, job.id, claimed.lease_token
    ) is True


def test_expired_lease_cannot_finish_job(database):
    from datetime import timedelta

    from sqlalchemy import func, update

    from intentcut.backend.storage.database_models import AIJob

    project = database.create_project("Expired Fencing Test")
    job = database.create_ai_job(
        project.id,
        {"kind": "first_cut"},
    )

    claimed = database.claim_next_ai_job()
    assert claimed is not None
    assert claimed.lease_token is not None

    # Force expiration directly in PostgreSQL.
    with database.engine.begin() as connection:
        connection.execute(
            update(AIJob)
            .where(AIJob.id == job.id)
            .values(
                lease_expires_at=(
                    func.clock_timestamp() - timedelta(seconds=1)
                )
            )
        )

    assert database.complete_ai_job(
        project.id, job.id, claimed.lease_token
    ) is False

    assert database.fail_ai_job(
        project.id,
        job.id,
        claimed.lease_token,
        "render_failed",
    ) is False

    persisted = database.get_ai_job(project.id, job.id)

    assert persisted is not None
    assert persisted.status == AIJobStatus.RUNNING.value


def test_claim_creates_lease_metadata(database):
    project = database.create_project("Lease Claim Test")

    original = database.create_ai_job(
        project.id,
        {"kind": "first_cut"},
    )

    claimed = database.claim_next_ai_job(lease_seconds=60)

    assert claimed is not None
    assert claimed.id == original.id
    assert claimed.status == AIJobStatus.RUNNING.value
    assert claimed.lease_token is not None
    assert claimed.lease_expires_at is not None
    assert claimed.attempt_count == 1

    persisted = database.get_ai_job(project.id, original.id)

    assert persisted is not None
    assert persisted.lease_token == claimed.lease_token
    assert persisted.lease_expires_at == claimed.lease_expires_at


def test_heartbeat_requires_correct_lease_token(database):
    project = database.create_project("Heartbeat Test")

    job = database.create_ai_job(
        project.id,
        {"kind": "first_cut"},
    )

    claimed = database.claim_next_ai_job(lease_seconds=30)

    assert claimed is not None
    assert claimed.lease_token is not None

    original_expiry = claimed.lease_expires_at

    # A different token must not renew the job.
    assert database.heartbeat_ai_job(
        project.id,
        job.id,
        uuid4(),
        lease_seconds=180,
    ) is False

    # The actual owner can extend its active lease.
    assert database.heartbeat_ai_job(
        project.id,
        job.id,
        claimed.lease_token,
        lease_seconds=180,
    ) is True

    persisted = database.get_ai_job(project.id, job.id)

    assert persisted is not None
    assert persisted.lease_expires_at > original_expiry


def test_expired_lease_rejects_heartbeat(database):
    from datetime import timedelta

    from sqlalchemy import func, update

    from intentcut.backend.storage.database_models import AIJob

    project = database.create_project("Expired Lease Test")

    job = database.create_ai_job(
        project.id,
        {"kind": "first_cut"},
    )

    claimed = database.claim_next_ai_job()

    assert claimed is not None
    assert claimed.lease_token is not None

    # Simulate time passing without sleeping.
    with database.engine.begin() as connection:
        connection.execute(
            update(AIJob)
            .where(AIJob.id == job.id)
            .values(
                lease_expires_at=func.now() - timedelta(seconds=1)
            )
        )

    assert database.heartbeat_ai_job(
        project.id,
        job.id,
        claimed.lease_token,
    ) is False


def _expire_job(database, job_id):
    """Force a lease to expire without time.sleep()."""
    from datetime import timedelta

    from sqlalchemy import func, update

    from intentcut.backend.storage.database_models import AIJob

    with database.engine.begin() as connection:
        connection.execute(
            update(AIJob)
            .where(AIJob.id == job_id)
            .values(
                lease_expires_at=(
                    func.clock_timestamp()
                    - timedelta(seconds=1)
                )
            )
        )


def test_recovery_requeues_expired_job(database):
    project = database.create_project("Recovery Retry")

    job = database.create_ai_job(
        project.id, {"kind": "first_cut"}
    )

    first = database.claim_next_ai_job()
    assert first is not None
    assert first.lease_token is not None

    old_token = first.lease_token

    _expire_job(database, job.id)

    recovered = database.recover_expired_ai_job(
        max_attempts=2
    )

    assert recovered is not None
    assert recovered.id == job.id
    assert recovered.status == AIJobStatus.QUEUED.value
    assert recovered.lease_token is None

    second = database.claim_next_ai_job()

    assert second is not None
    assert second.id == job.id
    assert second.status == AIJobStatus.RUNNING.value
    assert second.attempt_count == 2
    assert second.lease_token != old_token

    # Worker A has lost ownership permanently.
    assert database.complete_ai_job(
        project.id, job.id, old_token
    ) is False

    # Worker B still owns the job.
    assert database.complete_ai_job(
        project.id, job.id, second.lease_token
    ) is True


def test_recovery_fails_job_at_attempt_limit(database):
    project = database.create_project("Recovery Limit")

    job = database.create_ai_job(
        project.id, {"kind": "first_cut"}
    )

    claimed = database.claim_next_ai_job()
    assert claimed is not None

    _expire_job(database, job.id)

    recovered = database.recover_expired_ai_job(
        max_attempts=1
    )

    assert recovered is not None
    assert recovered.status == AIJobStatus.FAILED.value
    assert recovered.error_code == "worker_lease_expired"
    assert recovered.finished_at is not None
    assert recovered.lease_token is None
    assert recovered.lease_expires_at is None

    # Failed jobs cannot be claimed again.
    assert database.claim_next_ai_job() is None


def test_recovery_ignores_active_lease(database):
    project = database.create_project("Active Worker")

    job = database.create_ai_job(
        project.id, {"kind": "first_cut"}
    )

    claimed = database.claim_next_ai_job(
        lease_seconds=120
    )

    assert claimed is not None

    assert database.recover_expired_ai_job(
        max_attempts=2
    ) is None

    persisted = database.get_ai_job(
        project.id, job.id
    )

    assert persisted is not None
    assert persisted.status == AIJobStatus.RUNNING.value
    assert persisted.lease_token == claimed.lease_token


@pytest.mark.parametrize(
    "max_attempts",
    [0, -1, True, 4],
)
def test_recovery_rejects_invalid_attempt_limit(
    database, max_attempts
):
    with pytest.raises(
        ValueError, match="Invalid maximum attempts"
    ):
        database.recover_expired_ai_job(
            max_attempts=max_attempts
        )
