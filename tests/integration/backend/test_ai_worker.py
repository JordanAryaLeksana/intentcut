
from threading import Event

from intentcut.backend.ai_processing_adapter import ProcessingResult
from intentcut.backend.ai_worker import AIJobWorker
from intentcut.backend.jobs.domain import AIJobStatus


def test_worker_completes_successful_job(database):
    project = database.create_project("Worker Success")
    job = database.create_ai_job(
        project.id,
        {"kind": "first_cut"},
    )

    processed = []

    def fake_processor(claimed_job):
        processed.append(claimed_job.id)

    worker = AIJobWorker(
        database=database,
        processor=fake_processor,
        allow_artifact_free_processor=True,
    )

    assert worker.process_one() is True
    assert processed == [job.id]

    persisted = database.get_ai_job(project.id, job.id)

    assert persisted is not None
    assert persisted.status == AIJobStatus.SUCCEEDED.value
    assert persisted.finished_at is not None
    assert persisted.lease_token is None


def test_worker_records_processing_failure(database):
    project = database.create_project("Worker Failure")
    job = database.create_ai_job(
        project.id,
        {"kind": "first_cut"},
    )

    def failing_processor(claimed_job):
        raise RuntimeError("Simulated processor error")

    worker = AIJobWorker(
        database=database,
        processor=failing_processor,
    )

    assert worker.process_one() is True

    persisted = database.get_ai_job(project.id, job.id)

    assert persisted is not None
    assert persisted.status == AIJobStatus.FAILED.value
    assert persisted.error_code == "processing_failed"
    assert persisted.finished_at is not None
    assert persisted.lease_token is None


def test_worker_does_nothing_when_queue_empty(database):
    calls = []

    def fake_processor(claimed_job):
        calls.append(claimed_job.id)

    worker = AIJobWorker(
        database=database,
        processor=fake_processor,
        allow_artifact_free_processor=True,
    )

    assert worker.process_one() is False
    assert calls == []

def test_worker_renews_lease_during_processing(
    database,
    monkeypatch,
):
    project = database.create_project("Heartbeat Integration")
    job = database.create_ai_job(
        project.id,
        {"kind": "first_cut"},
    )

    heartbeat_called = Event()
    real_heartbeat = database.heartbeat_ai_job

    def observed_heartbeat(*args, **kwargs):
        renewed = real_heartbeat(*args, **kwargs)
        if renewed:
            heartbeat_called.set()
        return renewed

    monkeypatch.setattr(
        database,
        "heartbeat_ai_job",
        observed_heartbeat,
    )

    def processor(claimed):
        assert claimed.id == job.id
        assert heartbeat_called.wait(timeout=5)
        return None

    worker = AIJobWorker(
        database,
        processor,
        allow_artifact_free_processor=True,
        lease_seconds=10,
        heartbeat_interval_seconds=0.1,
    )

    assert worker.process_one() is True

    persisted = database.get_ai_job(project.id, job.id)

    assert persisted is not None
    assert persisted.status == AIJobStatus.SUCCEEDED.value
    assert heartbeat_called.is_set()


def test_worker_rejects_missing_video_artifact(
    database,
    tmp_path,
):
    project = database.create_project("Missing Artifact")
    job = database.create_ai_job(
        project.id,
        {"kind": "first_cut"},
    )

    storyboard = tmp_path / "storyboard.json"
    storyboard.write_text("{}", encoding="utf-8")

    def processor(claimed):
        return ProcessingResult(
            storyboard_path=storyboard,
            staged_video_path=tmp_path / "missing.mp4",
        )

    worker = AIJobWorker(database, processor)

    assert worker.process_one() is True

    persisted = database.get_ai_job(project.id, job.id)

    assert persisted is not None
    assert persisted.status == AIJobStatus.FAILED.value
    assert persisted.error_code == "processing_failed"
