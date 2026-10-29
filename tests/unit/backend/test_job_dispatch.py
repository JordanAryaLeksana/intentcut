"""Exact routing and output contracts; no provider or database access."""

from pathlib import Path
from unittest.mock import Mock
from uuid import uuid4

import pytest

from intentcut.backend.ai_worker import AIJobWorker
from intentcut.backend.contracts import (
    AIProcessingError,
    ProcessingResult,
    ProposalResult,
)
from intentcut.backend.jobs.dispatch import JobDispatcher, JobRegistration, JobType
from intentcut.backend.storage.database_models import AIJob


def job(payload):
    return AIJob(
        id=uuid4(),
        project_id=uuid4(),
        request_payload=payload,
        status="running",
        lease_token=uuid4(),
    )


def outputs():
    return ProcessingResult(Path("storyboard.json"), Path("video.mp4")), ProposalResult(
        {}
    )


@pytest.mark.parametrize(
    "kind",
    [JobType.UPLOADED_FIRST_CUT, JobType.MANUAL_RENDER, JobType.SEQUENCE_REVISION],
)
def test_exact_routing_calls_only_registered_handler(kind):
    media, proposal = outputs()
    existing_types = (
        JobType.UPLOADED_FIRST_CUT,
        JobType.MANUAL_RENDER,
        JobType.SEQUENCE_REVISION,
    )
    handlers = {
        t: Mock(return_value=proposal if t is JobType.SEQUENCE_REVISION else media)
        for t in existing_types
    }
    dispatcher = JobDispatcher(
        [
            JobRegistration(
                t,
                handler,
                ProposalResult if t is JobType.SEQUENCE_REVISION else ProcessingResult,
            )
            for t, handler in handlers.items()
        ]
    )
    claimed = job({"pipeline_version": kind.value})
    result = dispatcher(claimed)
    assert result is (proposal if kind is JobType.SEQUENCE_REVISION else media)
    handlers[kind].assert_called_once_with(claimed)
    for other, handler in handlers.items():
        if other != kind:
            handler.assert_not_called()
    assert set(dispatcher.supported_job_types) == {t.value for t in existing_types}


@pytest.mark.parametrize(
    "value",
    [
        None,
        "",
        "first_cut",
        "uploaded_v2",
        "voice_v1",
        "manual_v1 ",
        "MANUAL_V1",
        1,
        True,
        [],
        {},
    ],
)
def test_unknown_or_malformed_types_never_fall_back_to_first_cut(value):
    handler = Mock()
    dispatcher = JobDispatcher(
        [JobRegistration(JobType.UPLOADED_FIRST_CUT, handler, ProcessingResult)]
    )
    with pytest.raises(AIProcessingError) as exc:
        dispatcher(job({"pipeline_version": value, "kind": "first_cut"}))
    assert exc.value.code == "unsupported_job_type"
    handler.assert_not_called()


def test_missing_pipeline_is_not_inferred_from_legacy_kind():
    handler = Mock()
    dispatcher = JobDispatcher(
        [JobRegistration(JobType.UPLOADED_FIRST_CUT, handler, ProcessingResult)]
    )
    with pytest.raises(AIProcessingError, match="unsupported_job_type"):
        dispatcher(job({"kind": "first_cut"}))
    handler.assert_not_called()


def test_valid_type_not_supported_by_this_pool_is_rejected():
    handler = Mock()
    dispatcher = JobDispatcher(
        [JobRegistration(JobType.MANUAL_RENDER, handler, ProcessingResult)]
    )
    with pytest.raises(AIProcessingError, match="unsupported_job_type"):
        dispatcher(job({"pipeline_version": "revision_v1"}))
    handler.assert_not_called()


@pytest.mark.parametrize("result", [None, ProposalResult({}), "private-invalid-result"])
def test_wrong_output_cannot_reach_another_completion_path(result):
    dispatcher = JobDispatcher(
        [
            JobRegistration(
                JobType.MANUAL_RENDER, Mock(return_value=result), ProcessingResult
            )
        ]
    )
    with pytest.raises(AIProcessingError, match="processing_failed"):
        dispatcher(job({"pipeline_version": "manual_v1"}))


def test_registration_is_validated_and_snapshot_is_immutable():
    registration = JobRegistration(JobType.MANUAL_RENDER, Mock(), ProcessingResult)
    entries = [registration]
    dispatcher = JobDispatcher(entries)
    entries.clear()
    assert dispatcher.supported_job_types == ("manual_v1",)
    assert dispatcher.requires_artifact_publisher
    with pytest.raises(ValueError, match="Duplicate"):
        JobDispatcher([registration, registration])
    with pytest.raises(ValueError, match="At least one"):
        JobDispatcher([])
    with pytest.raises(ValueError, match="explicit JobType"):
        JobDispatcher([JobRegistration("future_v1", Mock(), ProcessingResult)])
    with pytest.raises(ValueError, match="result contract"):
        JobDispatcher(
            [JobRegistration(JobType.UPLOADED_FIRST_CUT, Mock(), ProposalResult)]
        )
    with pytest.raises(ValueError, match="callable"):
        JobDispatcher([JobRegistration(JobType.MANUAL_RENDER, None, ProcessingResult)])


def test_registered_render_requires_publisher_and_cannot_enable_synthetic_mode():
    dispatcher = JobDispatcher(
        [JobRegistration(JobType.MANUAL_RENDER, Mock(), ProcessingResult)]
    )
    with pytest.raises(ValueError, match="artifact publication"):
        AIJobWorker(Mock(), dispatcher)
    with pytest.raises(ValueError, match="artifact publication"):
        AIJobWorker(
            Mock(),
            dispatcher,
            artifact_publisher=Mock(),
            allow_artifact_free_processor=True,
        )


def test_worker_defensive_rejection_uses_current_lease_and_safe_error_only():
    database = Mock()
    claimed = job({"pipeline_version": "unknown_private_payload"})
    database.claim_next_ai_job.return_value = claimed
    handler = Mock()
    dispatcher = JobDispatcher(
        [JobRegistration(JobType.MANUAL_RENDER, handler, ProcessingResult)]
    )
    publisher = Mock()
    worker = AIJobWorker(database, dispatcher, artifact_publisher=publisher)
    assert worker.process_one()
    database.claim_next_ai_job.assert_called_once_with(
        lease_seconds=300, supported_job_types=("manual_v1",)
    )
    database.fail_ai_job.assert_called_once_with(
        project_id=claimed.project_id,
        job_id=claimed.id,
        lease_token=claimed.lease_token,
        error_code="unsupported_job_type",
    )
    handler.assert_not_called()
    publisher.publish_and_complete.assert_not_called()
    database.complete_ai_job.assert_not_called()
