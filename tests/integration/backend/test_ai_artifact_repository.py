"""Real PostgreSQL transactions, competing completions, and filesystem compensation."""

import hashlib
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from threading import Barrier, Event
from uuid import uuid4

import pytest
from sqlalchemy import event, func, insert, select, update
from sqlalchemy.exc import IntegrityError, SQLAlchemyError

from intentcut.backend.ai_artifacts import AIArtifactPublisher
from intentcut.backend.ai_worker import AIJobWorker
from intentcut.backend.database import CommitOutcomeUnknown
from intentcut.backend.database_models import AIJob, AIJobArtifact
from intentcut.backend.local_media_storage import LocalMediaStorage

pytestmark = [pytest.mark.integration, pytest.mark.postgres]


@pytest.fixture
def claimed(database):
    project = database.create_project("Persistent artifacts")
    database.create_ai_job(project.id, {"kind": "first_cut"})
    return database.claim_next_ai_job()


def records(job):
    result = []
    for kind in ("video", "storyboard"):
        artifact_id = uuid4()
        result.append(
            AIJobArtifact(
                id=artifact_id,
                job_id=job.id,
                kind=kind,
                storage_key=LocalMediaStorage.storage_key(job.project_id, artifact_id),
                size_bytes=100,
                sha256="a" * 64,
            )
        )
    return result


def complete(database, job, artifacts=None, **kwargs):
    return database.complete_ai_job_with_artifacts(
        kwargs.get("project_id", job.project_id),
        job.id,
        kwargs.get("token", job.lease_token),
        records(job) if artifacts is None else artifacts,
    )


def expire(database, job):
    with database.engine.begin() as connection:
        connection.execute(
            update(AIJob)
            .where(AIJob.id == job.id)
            .values(lease_expires_at=func.clock_timestamp() - timedelta(seconds=1))
        )


def test_atomic_completion_and_project_scoped_references(database, claimed):
    artifacts = records(claimed)
    assert complete(database, claimed, artifacts)
    job = database.get_ai_job(claimed.project_id, claimed.id)
    saved = database.list_ai_job_artifacts(claimed.project_id, claimed.id)
    assert job.status == "succeeded"
    assert job.finished_at is not None
    assert job.lease_token is None and job.lease_expires_at is None
    assert {a.id for a in saved} == {a.id for a in artifacts}
    assert {a.kind for a in saved} == {"video", "storyboard"}
    assert all(a.created_at is not None for a in saved)
    assert database.list_ai_job_artifacts(uuid4(), claimed.id) == []
    assert complete(database, claimed) is False
    assert len(database.list_ai_job_artifacts(claimed.project_id, claimed.id)) == 2


@pytest.mark.parametrize(
    "rejection", ["wrong_token", "wrong_project", "expired", "queued"]
)
def test_fencing_rejects_without_inserting(database, claimed, rejection):
    kwargs = {}
    if rejection == "wrong_token":
        kwargs["token"] = uuid4()
    elif rejection == "wrong_project":
        kwargs["project_id"] = uuid4()
        # Keys must be consistent with the requested project to reach DB fencing.
    elif rejection == "expired":
        expire(database, claimed)
    else:
        with database.engine.begin() as connection:
            connection.execute(
                update(AIJob).where(AIJob.id == claimed.id).values(status="queued")
            )
    artifacts = records(claimed)
    if rejection == "wrong_project":
        for artifact in artifacts:
            artifact.storage_key = LocalMediaStorage.storage_key(
                kwargs["project_id"], artifact.id
            )
    assert complete(database, claimed, artifacts, **kwargs) is False
    assert database.list_ai_job_artifacts(claimed.project_id, claimed.id) == []
    assert database.get_ai_job(claimed.project_id, claimed.id).status != "succeeded"


@pytest.mark.parametrize("invalid", ["missing", "duplicate", "job", "path", "token"])
def test_invalid_completion_batch(database, claimed, invalid):
    artifacts = records(claimed)
    kwargs = {}
    if invalid == "missing":
        artifacts.pop()
    elif invalid == "duplicate":
        artifacts[1].kind = "video"
    elif invalid == "job":
        artifacts[1].job_id = uuid4()
    elif invalid == "path":
        artifacts[1].storage_key = "../outside"
    else:
        kwargs["token"] = "invalid"
    with pytest.raises(ValueError):
        complete(database, claimed, artifacts, **kwargs)
    assert database.list_ai_job_artifacts(claimed.project_id, claimed.id) == []
    assert database.get_ai_job(claimed.project_id, claimed.id).status == "running"


def test_insert_constraint_failure_rolls_back_entire_completion(database, claimed):
    artifacts = records(claimed)
    artifacts[1].sha256 = "invalid"
    with pytest.raises(IntegrityError):
        complete(database, claimed, artifacts)
    assert database.list_ai_job_artifacts(claimed.project_id, claimed.id) == []
    assert database.get_ai_job(claimed.project_id, claimed.id).status == "running"


def test_transition_failure_rolls_back_already_flushed_artifacts(database, claimed):
    def fail_transition(
        connection, cursor, statement, parameters, context, executemany
    ):
        if statement.startswith("UPDATE ai_jobs"):
            # A separate reader cannot see the uncommitted artifact inserts.
            assert database.list_ai_job_artifacts(claimed.project_id, claimed.id) == []
            raise RuntimeError("injected transition failure")

    event.listen(database.engine, "before_cursor_execute", fail_transition)
    try:
        with pytest.raises(RuntimeError, match="transition failure"):
            complete(database, claimed)
    finally:
        event.remove(database.engine, "before_cursor_execute", fail_transition)
    assert database.list_ai_job_artifacts(claimed.project_id, claimed.id) == []
    assert database.get_ai_job(claimed.project_id, claimed.id).status == "running"


def test_duplicate_kind_constraint_rolls_back_other_artifact(database, claimed):
    existing = records(claimed)[0]
    with database._sessions.begin() as session:
        session.add(existing)
    with pytest.raises(IntegrityError):
        complete(database, claimed)
    actual = database.list_ai_job_artifacts(claimed.project_id, claimed.id)
    assert [a.id for a in actual] == [existing.id]
    assert database.get_ai_job(claimed.project_id, claimed.id).status == "running"


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("kind", "thumbnail"),
        ("size_bytes", 0),
        ("size_bytes", -1),
        ("sha256", "a" * 63),
        ("sha256", "G" * 64),
        ("storage_key", "../escape"),
        ("storage_key", "/absolute"),
        ("storage_key", "projects/../../outside/original"),
        ("job_id", uuid4()),
    ],
)
def test_database_enforces_artifact_constraints(database, claimed, field, value):
    artifact = records(claimed)[0]
    data = {
        name: getattr(artifact, name)
        for name in ("id", "job_id", "kind", "size_bytes", "sha256", "storage_key")
    }
    data[field] = value
    with pytest.raises(IntegrityError), database.engine.begin() as connection:
        connection.execute(insert(AIJobArtifact).values(**data))


def test_competing_completions_have_one_winner(database, claimed):
    barrier = Barrier(2)

    def contender():
        artifacts = records(claimed)
        barrier.wait(timeout=5)
        return complete(database, claimed, artifacts), {a.id for a in artifacts}

    with ThreadPoolExecutor(max_workers=2) as pool:
        outcomes = list(pool.map(lambda _: contender(), range(2)))
    assert sorted(success for success, _ in outcomes) == [False, True]
    winner = next(ids for success, ids in outcomes if success)
    assert {
        a.id for a in database.list_ai_job_artifacts(claimed.project_id, claimed.id)
    } == winner


def test_expiry_while_waiting_for_row_lock_rejects_completion(database, claimed):
    waiting = Event()

    def observe(connection, cursor, statement, parameters, context, executemany):
        if "FOR UPDATE" in statement:
            waiting.set()

    with ThreadPoolExecutor(max_workers=1) as pool:
        with database.engine.begin() as connection:
            connection.execute(
                select(AIJob).where(AIJob.id == claimed.id).with_for_update()
            )
            event.listen(database.engine, "before_cursor_execute", observe)
            future = pool.submit(complete, database, claimed)
            try:
                assert waiting.wait(timeout=5)
                assert not future.done()
                connection.execute(
                    update(AIJob)
                    .where(AIJob.id == claimed.id)
                    .values(
                        lease_expires_at=func.clock_timestamp() - timedelta(seconds=1)
                    )
                )
            finally:
                event.remove(database.engine, "before_cursor_execute", observe)
        assert future.result(timeout=5) is False
    assert database.list_ai_job_artifacts(claimed.project_id, claimed.id) == []


def test_expiry_after_insert_rolls_back_artifacts(database, claimed):
    def expire_in_transaction(session, flush_context):
        session.execute(
            update(AIJob)
            .where(AIJob.id == claimed.id)
            .values(lease_expires_at=func.clock_timestamp() - timedelta(seconds=1))
        )

    event.listen(database._sessions, "after_flush_postexec", expire_in_transaction)
    try:
        assert complete(database, claimed) is False
    finally:
        event.remove(database._sessions, "after_flush_postexec", expire_in_transaction)
    assert database.list_ai_job_artifacts(claimed.project_id, claimed.id) == []
    assert database.get_ai_job(claimed.project_id, claimed.id).status == "running"


@pytest.mark.parametrize("commit_happened", [False, True])
def test_repository_distinguishes_uncertain_commit(
    database, claimed, monkeypatch, commit_happened
):
    original = database._sessions.class_.commit

    def disconnect(session):
        if commit_happened:
            original(session)
        raise SQLAlchemyError("lost connection during commit")

    with monkeypatch.context() as patch:
        patch.setattr(database._sessions.class_, "commit", disconnect)
        with pytest.raises(CommitOutcomeUnknown):
            complete(database, claimed)
    assert database.get_ai_job(claimed.project_id, claimed.id).status == (
        "succeeded" if commit_happened else "running"
    )
    assert len(database.list_ai_job_artifacts(claimed.project_id, claimed.id)) == (
        2 if commit_happened else 0
    )


def test_session_cleanup_failure_after_commit_is_uncertain(
    database, claimed, monkeypatch
):
    original = database._sessions.class_.close

    def fail_close(session):
        original(session)
        raise SQLAlchemyError("connection return failed")

    with monkeypatch.context() as patch:
        patch.setattr(database._sessions.class_, "close", fail_close)
        with pytest.raises(CommitOutcomeUnknown):
            complete(database, claimed)
    assert database.get_ai_job(claimed.project_id, claimed.id).status == "succeeded"
    assert len(database.list_ai_job_artifacts(claimed.project_id, claimed.id)) == 2


def test_schema_initialization_preserves_existing_data(database, claimed):
    assert complete(database, claimed)
    before = database.list_ai_job_artifacts(claimed.project_id, claimed.id)
    database.initialize_schema()
    after = database.list_ai_job_artifacts(claimed.project_id, claimed.id)
    assert [a.id for a in before] == [a.id for a in after]
    assert database.get_ai_job(claimed.project_id, claimed.id).status == "succeeded"


def test_worker_persists_real_files(database, storage, processing_result):
    project = database.create_project("Worker artifacts")
    job = database.create_ai_job(project.id, {"kind": "first_cut"})
    worker = AIJobWorker(
        database,
        lambda _: processing_result,
        artifact_publisher=AIArtifactPublisher(storage),
    )
    assert worker.process_one()
    assert database.get_ai_job(project.id, job.id).status == "succeeded"
    artifacts = database.list_ai_job_artifacts(project.id, job.id)
    assert {a.kind for a in artifacts} == {"video", "storyboard"}
    for artifact in artifacts:
        path = storage.root / artifact.storage_key
        assert path.stat().st_size == artifact.size_bytes
        assert hashlib.sha256(path.read_bytes()).hexdigest() == artifact.sha256
    assert list((storage.root / ".staging").iterdir()) == []


@pytest.mark.parametrize(
    "fault", ["no_result", "no_publisher", "corrupt", "publication", "rollback"]
)
def test_worker_cannot_succeed_without_committed_artifacts(
    database, storage, processing_result, monkeypatch, fault
):
    project = database.create_project("Worker rejection")
    job = database.create_ai_job(project.id, {"kind": "first_cut"})
    if fault == "corrupt":
        processing_result.staged_video_path.write_bytes(b"corrupt")
    elif fault == "publication":

        def denied(*args):
            raise PermissionError("denied")

        monkeypatch.setattr(storage, "publish", denied)
    elif fault == "rollback":

        def rollback(*args):
            raise SQLAlchemyError("known rollback before commit")

        monkeypatch.setattr(database, "complete_ai_job_with_artifacts", rollback)
    worker = AIJobWorker(
        database,
        lambda _: None if fault == "no_result" else processing_result,
        artifact_publisher=None
        if fault == "no_publisher"
        else AIArtifactPublisher(storage),
    )
    assert worker.process_one()
    assert database.get_ai_job(project.id, job.id).status == "failed"
    assert database.list_ai_job_artifacts(project.id, job.id) == []
    assert not list(storage.root.glob("projects/*/*/original"))


@pytest.mark.parametrize("commit_happened", [False, True])
def test_worker_preserves_files_after_commit_ack_loss(
    database, storage, processing_result, monkeypatch, commit_happened
):
    project = database.create_project("Uncertain worker")
    job = database.create_ai_job(project.id, {"kind": "first_cut"})
    original = database.complete_ai_job_with_artifacts

    def lose_ack(*args):
        if commit_happened:
            assert original(*args)
        raise CommitOutcomeUnknown

    monkeypatch.setattr(database, "complete_ai_job_with_artifacts", lose_ack)
    worker = AIJobWorker(
        database,
        lambda _: processing_result,
        artifact_publisher=AIArtifactPublisher(storage),
    )
    assert worker.process_one()
    persisted = database.get_ai_job(project.id, job.id)
    assert persisted.status == ("succeeded" if commit_happened else "running")
    assert len(list(storage.root.glob("projects/*/*/original"))) == 2
    assert len(database.list_ai_job_artifacts(project.id, job.id)) == (
        2 if commit_happened else 0
    )


def test_heartbeat_continues_during_publication(
    database, storage, processing_result, monkeypatch
):
    project = database.create_project("Heartbeat through publication")
    job = database.create_ai_job(project.id, {"kind": "first_cut"})
    publishing = Event()
    renewed = Event()
    original_heartbeat = database.heartbeat_ai_job
    original_publish = storage.publish

    def heartbeat(*args, **kwargs):
        result = original_heartbeat(*args, **kwargs)
        if result and publishing.is_set():
            renewed.set()
        return result

    def publish(*args):
        publishing.set()
        assert renewed.wait(timeout=5)
        return original_publish(*args)

    monkeypatch.setattr(database, "heartbeat_ai_job", heartbeat)
    monkeypatch.setattr(storage, "publish", publish)
    worker = AIJobWorker(
        database,
        lambda _: processing_result,
        artifact_publisher=AIArtifactPublisher(storage),
        lease_seconds=10,
        heartbeat_interval_seconds=0.05,
    )
    assert worker.process_one()
    assert renewed.is_set()
    assert database.get_ai_job(project.id, job.id).status == "succeeded"


def test_stale_attempt_cannot_replace_winners_files(
    database, claimed, storage, processing_result
):
    expire(database, claimed)
    database.recover_expired_ai_job(max_attempts=2)
    current = database.claim_next_ai_job()
    publisher = AIArtifactPublisher(storage)
    assert publisher.publish_and_complete(
        database, current.project_id, current.id, current.lease_token, processing_result
    )
    files = {p: p.read_bytes() for p in storage.root.glob("projects/*/*/original")}
    assert (
        publisher.publish_and_complete(
            database,
            claimed.project_id,
            claimed.id,
            claimed.lease_token,
            processing_result,
        )
        is False
    )
    assert {
        p: p.read_bytes() for p in storage.root.glob("projects/*/*/original")
    } == files
    assert len(database.list_ai_job_artifacts(claimed.project_id, claimed.id)) == 2


def test_concurrent_publications_retain_only_winners_files(
    database, claimed, storage, processing_result, monkeypatch
):
    original = database.complete_ai_job_with_artifacts
    barrier = Barrier(2)

    def synchronized(*args):
        barrier.wait(timeout=5)
        return original(*args)

    monkeypatch.setattr(database, "complete_ai_job_with_artifacts", synchronized)
    publisher = AIArtifactPublisher(storage)

    def contender(_):
        return publisher.publish_and_complete(
            database,
            claimed.project_id,
            claimed.id,
            claimed.lease_token,
            processing_result,
        )

    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sorted(pool.map(contender, range(2))) == [False, True]
    actual = database.list_ai_job_artifacts(claimed.project_id, claimed.id)
    assert {storage.root / a.storage_key for a in actual} == set(
        storage.root.glob("projects/*/*/original")
    )
    assert len(actual) == 2
    assert list((storage.root / ".staging").iterdir()) == []
