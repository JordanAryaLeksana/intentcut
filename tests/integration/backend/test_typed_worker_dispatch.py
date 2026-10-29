"""Capabilities fence PostgreSQL claiming and recovery before any execution."""

from datetime import timedelta
from unittest.mock import Mock
from uuid import uuid4

import pytest
from sqlalchemy import func, update

from intentcut.backend.ai_worker import AIJobWorker
from intentcut.backend.contracts import ProcessingResult, ProposalResult
from intentcut.backend.jobs.dispatch import JobDispatcher, JobRegistration, JobType
from intentcut.backend.storage.database_models import AIJob

pytestmark = [pytest.mark.integration, pytest.mark.postgres]


def queued(database, kind):
    project = database.create_project("Typed dispatch")
    return database.create_ai_job(project.id, {"pipeline_version": kind})


def expire(database, job):
    with database.engine.begin() as connection:
        connection.execute(
            update(AIJob)
            .where(AIJob.id == job.id)
            .values(lease_expires_at=func.clock_timestamp() - timedelta(seconds=1))
        )


def test_pool_skips_incompatible_unknown_and_unversioned_jobs(database):
    unknown = queued(database, "future_v1")
    revision = queued(database, "revision_v1")
    legacy = database.create_ai_job(unknown.project_id, {"kind": "first_cut"})
    manual = queued(database, "manual_v1")
    claim = database.claim_next_ai_job(supported_job_types=("manual_v1",))
    assert claim.id == manual.id and claim.attempt_count == 1
    for row in [unknown, revision, legacy]:
        persisted = database.get_ai_job(row.project_id, row.id)
        assert persisted.status == "queued" and persisted.attempt_count == 0
        assert persisted.lease_token is None and persisted.progress is None
    assert database.claim_next_ai_job(supported_job_types=("manual_v1",)) is None
    assert (
        database.claim_next_ai_job(
            job_id=revision.id, supported_job_types=("manual_v1",)
        )
        is None
    )
    assert database.claim_next_ai_job(supported_job_types=()) is None


def test_manual_only_intersects_registry_capabilities(database):
    manual = queued(database, "manual_v1")
    revision = queued(database, "revision_v1")
    assert (
        database.claim_next_ai_job(
            manual_only=True, supported_job_types=("revision_v1",)
        )
        is None
    )
    assert (
        database.claim_next_ai_job(
            manual_only=True, supported_job_types=("manual_v1", "revision_v1")
        ).id
        == manual.id
    )
    assert database.get_ai_job(revision.project_id, revision.id).status == "queued"


@pytest.mark.parametrize(
    "values", [("",), ("bad type",), (1,), "manual_v1", ["manual_v1"]]
)
def test_invalid_filter_fails_closed_without_claim(database, values):
    row = queued(database, "manual_v1")
    with pytest.raises(ValueError, match="supported job types"):
        database.claim_next_ai_job(supported_job_types=values)
    with pytest.raises(ValueError, match="supported job types"):
        database.recover_expired_ai_job(supported_job_types=values)
    assert database.get_ai_job(row.project_id, row.id).attempt_count == 0


def test_recovery_only_touches_supported_types_and_old_lease_is_fenced(database):
    revision = queued(database, "revision_v1")
    manual = queued(database, "manual_v1")
    revision_claim = database.claim_next_ai_job(job_id=revision.id)
    manual_claim = database.claim_next_ai_job(job_id=manual.id)
    expire(database, revision_claim)
    expire(database, manual_claim)
    assert (
        database.update_ai_job_progress(
            manual.project_id, manual.id, manual_claim.lease_token, "rendering_video"
        )
        is False
    )
    recovered = database.recover_expired_ai_job(
        max_attempts=2, supported_job_types=("manual_v1",)
    )
    assert recovered.id == manual.id and recovered.status == "queued"
    assert recovered.progress is None and recovered.lease_token is None
    assert (
        database.get_ai_job(revision.project_id, revision.id).lease_token
        == revision_claim.lease_token
    )
    replacement = database.claim_next_ai_job(supported_job_types=("manual_v1",))
    assert (
        replacement.attempt_count == 2
        and replacement.lease_token != manual_claim.lease_token
    )
    assert (
        database.complete_ai_job(manual.project_id, manual.id, manual_claim.lease_token)
        is False
    )
    assert (
        database.fail_ai_job(
            manual.project_id,
            manual.id,
            manual_claim.lease_token,
            "unsupported_job_type",
        )
        is False
    )
    assert database.recover_expired_ai_job(supported_job_types=("manual_v1",)) is None
    expire(database, replacement)
    assert (
        database.recover_expired_ai_job(
            max_attempts=2, supported_job_types=("manual_v1",)
        ).status
        == "failed"
    )


def test_unknown_target_is_not_claimed_or_executed(database):
    row = queued(database, "unsupported_v1")
    handler, publisher = Mock(), Mock()
    worker = AIJobWorker(
        database,
        JobDispatcher(
            [JobRegistration(JobType.MANUAL_RENDER, handler, ProcessingResult)]
        ),
        artifact_publisher=publisher,
    )
    assert worker.process_one(job_id=row.id) is False
    handler.assert_not_called()
    publisher.publish_and_complete.assert_not_called()
    assert database.get_ai_job(row.project_id, row.id).status == "queued"


def test_registered_result_cannot_publish_after_lease_replacement(
    database, processing_result
):
    row = queued(database, "manual_v1")
    replacements = []

    def handler(claimed):
        expire(database, claimed)
        database.recover_expired_ai_job(
            job_id=row.id, max_attempts=2, supported_job_types=("manual_v1",)
        )
        replacements.append(
            database.claim_next_ai_job(
                job_id=row.id, supported_job_types=("manual_v1",)
            )
        )
        return processing_result

    publisher = Mock()
    worker = AIJobWorker(
        database,
        JobDispatcher(
            [JobRegistration(JobType.MANUAL_RENDER, handler, ProcessingResult)]
        ),
        artifact_publisher=publisher,
    )
    assert worker.process_one(job_id=row.id)
    publisher.publish_and_complete.assert_not_called()
    current = database.get_ai_job(row.project_id, row.id)
    assert (
        current.status == "running"
        and current.lease_token == replacements[0].lease_token
    )
    assert not database.list_ai_job_artifacts(row.project_id, row.id)


def test_defensive_unsupported_failure_cannot_overwrite_replaced_lease(
    database, monkeypatch
):
    row = queued(database, "unsupported_v1")
    old = database.claim_next_ai_job(job_id=row.id)
    expire(database, old)
    database.recover_expired_ai_job(job_id=row.id, max_attempts=2)
    fresh = database.claim_next_ai_job(job_id=row.id)
    monkeypatch.setattr(database, "claim_next_ai_job", lambda **kw: old)
    dispatcher = JobDispatcher(
        [JobRegistration(JobType.SEQUENCE_REVISION, Mock(), ProposalResult)]
    )
    assert AIJobWorker(database, dispatcher).process_one(job_id=row.id)
    current = database.get_ai_job(row.project_id, row.id)
    assert current.status == "running" and current.lease_token == fresh.lease_token
    assert current.error_code is None
    assert database.heartbeat_ai_job(row.project_id, row.id, uuid4()) is False
