from threading import Event
from unittest.mock import Mock
from uuid import uuid4

import pytest

from intentcut.backend.ai_artifacts import AIArtifactPublisher
from intentcut.backend.ai_processing_adapter import RealAIProcessingAdapter
from intentcut.backend.ai_worker import AIJobWorker
from intentcut.backend.database import CommitOutcomeUnknown
from intentcut.backend.database_models import AIJob


@pytest.fixture
def claimed_database(database):
    database.claim_next_ai_job.return_value = AIJob(
        id=uuid4(), project_id=uuid4(), lease_token=uuid4(), status="running"
    )
    return database


@pytest.mark.parametrize("compatibility", [False, True])
def test_real_adapter_requires_publisher(database, storage, settings, compatibility):
    adapter = RealAIProcessingAdapter(
        database=database, storage=storage, settings=settings, muse=Mock()
    )
    with pytest.raises(ValueError, match="requires artifact publication"):
        AIJobWorker(database, adapter, allow_artifact_free_processor=compatibility)


def test_real_adapter_cannot_enable_artifact_free_mode(database, storage, settings):
    adapter = RealAIProcessingAdapter(
        database=database, storage=storage, settings=settings, muse=Mock()
    )
    with pytest.raises(ValueError, match="requires artifact publication"):
        AIJobWorker(
            database,
            adapter,
            artifact_publisher=Mock(spec=AIArtifactPublisher),
            allow_artifact_free_processor=True,
        )


def test_real_adapter_missing_result_fails(
    claimed_database, storage, settings, monkeypatch
):
    adapter = RealAIProcessingAdapter(
        database=claimed_database, storage=storage, settings=settings, muse=Mock()
    )
    monkeypatch.setattr(RealAIProcessingAdapter, "__call__", lambda self, job: None)
    publisher = Mock(spec=AIArtifactPublisher)
    worker = AIJobWorker(claimed_database, adapter, artifact_publisher=publisher)
    assert worker.process_one()
    claimed_database.fail_ai_job.assert_called_once()
    claimed_database.complete_ai_job.assert_not_called()
    publisher.publish_and_complete.assert_not_called()


def test_compatibility_cannot_skip_processing_result_publication(
    claimed_database, processing_result
):
    worker = AIJobWorker(
        claimed_database,
        lambda job: processing_result,
        allow_artifact_free_processor=True,
    )
    assert worker.process_one()
    claimed_database.fail_ai_job.assert_called_once()
    claimed_database.complete_ai_job.assert_not_called()


@pytest.mark.parametrize("heartbeat_result", [False, OSError("database unavailable")])
def test_heartbeat_loss_prevents_publication(
    claimed_database, processing_result, heartbeat_result
):
    called = Event()

    def heartbeat(**kwargs):
        called.set()
        if isinstance(heartbeat_result, Exception):
            raise heartbeat_result
        return heartbeat_result

    claimed_database.heartbeat_ai_job.side_effect = heartbeat
    publisher = Mock(spec=AIArtifactPublisher)

    def processor(job):
        assert called.wait(timeout=5)
        return processing_result

    worker = AIJobWorker(
        claimed_database,
        processor,
        artifact_publisher=publisher,
        lease_seconds=10,
        heartbeat_interval_seconds=0.01,
    )
    assert worker.process_one()
    claimed_database.complete_ai_job.assert_not_called()
    claimed_database.fail_ai_job.assert_not_called()
    # Even if the processor wakes just before ownership_lost is set, the
    # publisher's callback is required to gate publication and completion.
    if publisher.publish_and_complete.called:
        assert not publisher.publish_and_complete.call_args.kwargs["owns_lease"]()


def test_unknown_commit_never_marks_failed(claimed_database, processing_result):
    publisher = Mock(spec=AIArtifactPublisher)
    publisher.publish_and_complete.side_effect = CommitOutcomeUnknown
    worker = AIJobWorker(
        claimed_database, lambda job: processing_result, artifact_publisher=publisher
    )
    assert worker.process_one()
    claimed_database.fail_ai_job.assert_not_called()
    claimed_database.complete_ai_job.assert_not_called()
