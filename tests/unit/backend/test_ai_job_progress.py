from datetime import UTC, datetime, timedelta
from unittest.mock import Mock
from uuid import uuid4

import pytest
from pydantic import ValidationError

from intentcut.backend.ai_worker import AIJobWorker
from intentcut.backend.contracts import JobLeaseLost
from intentcut.backend.jobs.progress import AIJobProgress
from intentcut.backend.jobs.schemas import AIJobResponse


def payload(**changes):
    now = datetime.now(UTC)
    return {
        "stage": "understanding_footage",
        "stage_started_at": now,
        "updated_at": now,
        "completed_windows": 1,
        "total_windows": 2,
        **changes,
    }


@pytest.mark.parametrize(
    "changes",
    [
        {"stage": "private_prompt"},
        {"api_key": "secret"},
        {"completed_windows": -1},
        {"completed_windows": 3},
        {"completed_windows": True},
        {"total_windows": 0},
        {"total_windows": None},
        {"stage": "rendering_video"},
        {"updated_at": datetime.now(UTC) - timedelta(days=1)},
        {"stage_started_at": datetime.now().replace(tzinfo=None)},
    ],
)
def test_progress_contract_rejects_invalid_or_private_metadata(changes):
    with pytest.raises(ValidationError):
        AIJobProgress.model_validate(payload(**changes))


def test_legacy_job_response_does_not_require_progress():
    now = datetime.now(UTC)
    job = AIJobResponse(
        id=uuid4(),
        status="queued",
        created_at=now,
        updated_at=now,
        started_at=None,
        finished_at=None,
        attempt_count=0,
        error_code=None,
    )
    assert job.progress is None
    assert job.model_dump()["status"] == "queued"


def test_lost_progress_lease_stops_worker_without_failure(database):
    from intentcut.backend.storage.database_models import AIJob

    database.claim_next_ai_job.return_value = AIJob(
        id=uuid4(), project_id=uuid4(), lease_token=uuid4(), status="running"
    )
    processor = Mock(side_effect=JobLeaseLost())
    worker = AIJobWorker(database, processor)
    assert worker.process_one()
    database.fail_ai_job.assert_not_called()
    database.complete_ai_job.assert_not_called()


def test_publication_requires_a_live_progress_lease(database, processing_result):
    from intentcut.backend.storage.database_models import AIJob

    database.claim_next_ai_job.return_value = AIJob(
        id=uuid4(), project_id=uuid4(), lease_token=uuid4(), status="running"
    )
    database.update_ai_job_progress.return_value = False
    publisher = Mock()
    worker = AIJobWorker(
        database, lambda _: processing_result, artifact_publisher=publisher
    )
    assert worker.process_one()
    publisher.publish_and_complete.assert_not_called()
    database.fail_ai_job.assert_not_called()


@pytest.mark.parametrize("write_failure", [False, OSError("database unavailable")])
def test_progress_failure_stops_before_inference(
    database, storage, settings, write_failure
):
    from intentcut.backend.ai_processing_adapter import RealAIProcessingAdapter
    from intentcut.backend.contracts import AIProcessingError
    from intentcut.backend.storage.database_models import AIJob

    media_id = uuid4()
    job = AIJob(
        id=uuid4(),
        project_id=uuid4(),
        lease_token=uuid4(),
        status="running",
        lease_expires_at=datetime.now(UTC) + timedelta(minutes=5),
        request_payload={
            "kind": "first_cut",
            "intent": "Test",
            "target_seconds": 10,
            "media_ids": [str(media_id)],
            "pipeline_version": "uploaded_v1",
            "source_sha256": {str(media_id): "a" * 64},
        },
    )
    database.get_ai_job.return_value = job
    if isinstance(write_failure, Exception):
        database.update_ai_job_progress.side_effect = write_failure
        expected = AIProcessingError
    else:
        database.update_ai_job_progress.return_value = False
        expected = JobLeaseLost
    muse = Mock()
    adapter = RealAIProcessingAdapter(
        database=database, storage=storage, settings=settings, muse=muse
    )
    with pytest.raises(expected) as error:
        adapter(job)
    if expected is AIProcessingError:
        assert error.value.code == "processing_failed"
    muse.analyze.assert_not_called()
    muse.select.assert_not_called()
    database.get_media.assert_not_called()
