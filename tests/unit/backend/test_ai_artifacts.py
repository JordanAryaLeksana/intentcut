import hashlib
import os
from pathlib import Path
from unittest.mock import Mock
from uuid import uuid4

import pytest

from intentcut.backend.ai_artifacts import AIArtifactPublisher
from intentcut.backend.ai_processing_adapter import ProcessingResult
from intentcut.backend.storage.database import CommitOutcomeUnknown
from intentcut.backend.storage.local_media_storage import LocalMediaStorage
from intentcut.media.models import MediaError


@pytest.fixture
def artifact_storage(tmp_path):
    storage = LocalMediaStorage(tmp_path / "artifacts", 1024 * 1024, 1024)
    storage.initialize()
    return storage


@pytest.fixture
def publisher(artifact_storage):
    return AIArtifactPublisher(artifact_storage)


def publish(publisher, database, result, **kwargs):
    return publisher.publish_and_complete(
        database, uuid4(), uuid4(), uuid4(), result, **kwargs
    )


def finals(storage):
    return list(storage.root.glob("projects/*/*/original"))


def assert_clean(storage):
    assert not finals(storage)
    assert list((storage.root / ".staging").iterdir()) == []


def test_publishes_independent_copies_with_verified_metadata(
    publisher, artifact_storage, database, processing_result
):
    database.complete_ai_job_with_artifacts.return_value = True
    assert publish(publisher, database, processing_result)
    project_id, job_id, _, records = (
        database.complete_ai_job_with_artifacts.call_args.args
    )
    assert {a.kind for a in records} == {"video", "storyboard"}
    for record in records:
        path = artifact_storage.root / record.storage_key
        assert record.job_id == job_id
        assert record.storage_key == artifact_storage.storage_key(project_id, record.id)
        assert not Path(record.storage_key).is_absolute()
        assert record.size_bytes == path.stat().st_size
        assert record.sha256 == hashlib.sha256(path.read_bytes()).hexdigest()
        assert path.stat().st_nlink == 1  # Staging link was removed.
    processing_result.staged_video_path.write_bytes(b"changed workspace")
    video = next(a for a in records if a.kind == "video")
    assert (
        artifact_storage.root / video.storage_key
    ).read_bytes() != b"changed workspace"


@pytest.mark.parametrize(
    "damage",
    [
        "missing_video",
        "empty_video",
        "corrupt_video",
        "truncated_video",
        "missing_storyboard",
        "empty_storyboard",
        "invalid_json",
        "json_array",
        "video_symlink",
        "storyboard_symlink",
        "parent_symlink",
        "traversal",
        "fifo",
    ],
)
def test_invalid_outputs_never_register(
    damage, publisher, artifact_storage, database, processing_result, tmp_path
):
    video, board = (
        processing_result.staged_video_path,
        processing_result.storyboard_path,
    )
    if damage == "missing_video":
        video.unlink()
    elif damage == "empty_video":
        video.write_bytes(b"")
    elif damage == "corrupt_video":
        video.write_bytes(b"not an MP4")
    elif damage == "truncated_video":
        video.write_bytes(video.read_bytes()[:100])
    elif damage == "missing_storyboard":
        board.unlink()
    elif damage == "empty_storyboard":
        board.write_bytes(b"")
    elif damage == "invalid_json":
        board.write_text("{")
    elif damage == "json_array":
        board.write_text("[]")
    elif damage in {"video_symlink", "storyboard_symlink"}:
        original = video if damage == "video_symlink" else board
        destination = tmp_path / "saved"
        original.rename(destination)
        original.symlink_to(destination)
    elif damage == "parent_symlink":
        link = tmp_path / "linked"
        link.symlink_to(tmp_path, target_is_directory=True)
        processing_result = ProcessingResult(link / board.name, video)
    elif damage == "traversal":
        directory = tmp_path / "inner"
        directory.mkdir()
        processing_result = ProcessingResult(directory / ".." / board.name, video)
    elif damage == "fifo":
        video.unlink()
        os.mkfifo(video)
    with pytest.raises((OSError, ValueError, MediaError)):
        publish(publisher, database, processing_result)
    database.complete_ai_job_with_artifacts.assert_not_called()
    assert_clean(artifact_storage)


def test_partial_publication_failure_cleans_only_owned_files(
    publisher, artifact_storage, database, processing_result, monkeypatch
):
    database.complete_ai_job_with_artifacts.return_value = True
    publish(publisher, database, processing_result)
    existing = {path: path.read_bytes() for path in finals(artifact_storage)}
    database.reset_mock()
    original = artifact_storage.publish
    calls = 0

    def fail_second(*args):
        nonlocal calls
        calls += 1
        if calls == 2:
            raise OSError("injected publication failure")
        return original(*args)

    monkeypatch.setattr(artifact_storage, "publish", fail_second)
    with pytest.raises(OSError):
        publish(publisher, database, processing_result)
    assert {path: path.read_bytes() for path in finals(artifact_storage)} == existing
    database.complete_ai_job_with_artifacts.assert_not_called()
    assert list((artifact_storage.root / ".staging").iterdir()) == []


@pytest.mark.parametrize("outcome", [False, RuntimeError("known rollback")])
def test_known_database_rejection_cleans_publications(
    publisher, artifact_storage, database, processing_result, outcome
):
    if isinstance(outcome, Exception):
        database.complete_ai_job_with_artifacts.side_effect = outcome
        with pytest.raises(RuntimeError):
            publish(publisher, database, processing_result)
    else:
        database.complete_ai_job_with_artifacts.return_value = outcome
        assert publish(publisher, database, processing_result) is False
    assert_clean(artifact_storage)


@pytest.mark.parametrize("reconciliation", ["empty", "unavailable", "mismatch"])
def test_unknown_commit_never_deletes_files(
    publisher, artifact_storage, database, processing_result, reconciliation
):
    database.complete_ai_job_with_artifacts.side_effect = CommitOutcomeUnknown
    database.get_ai_job.return_value = Mock(status="succeeded")
    if reconciliation == "empty":
        database.list_ai_job_artifacts.return_value = []
    elif reconciliation == "unavailable":
        database.list_ai_job_artifacts.side_effect = OSError("database unavailable")
    else:
        database.list_ai_job_artifacts.return_value = [Mock()]
    with pytest.raises(CommitOutcomeUnknown):
        publish(publisher, database, processing_result)
    assert len(finals(artifact_storage)) == 2
    assert list((artifact_storage.root / ".staging").iterdir()) == []


@pytest.mark.parametrize("lost_after_publish", [False, True])
def test_lost_ownership_prevents_completion(
    publisher, artifact_storage, database, processing_result, lost_after_publish
):
    owns_lease = Mock(side_effect=[True, False] if lost_after_publish else [False])
    assert (
        publish(publisher, database, processing_result, owns_lease=owns_lease) is False
    )
    database.complete_ai_job_with_artifacts.assert_not_called()
    assert_clean(artifact_storage)


def test_published_checksum_is_verified(
    publisher, artifact_storage, database, processing_result, monkeypatch
):
    original = artifact_storage.publish

    def corrupt(*args):
        path = original(*args)
        path.write_bytes(b"corrupted after staging")
        return path

    monkeypatch.setattr(artifact_storage, "publish", corrupt)
    with pytest.raises(ValueError, match="checksum"):
        publish(publisher, database, processing_result)
    database.complete_ai_job_with_artifacts.assert_not_called()
    assert_clean(artifact_storage)


def test_staged_checksum_is_verified(
    publisher, artifact_storage, database, processing_result, monkeypatch
):
    original = artifact_storage.stage

    def corrupt(*args):
        staged = original(*args)
        staged.path.write_bytes(b"corrupted during copy")
        return staged

    monkeypatch.setattr(artifact_storage, "stage", corrupt)
    with pytest.raises(ValueError, match="checksum"):
        publish(publisher, database, processing_result)
    assert_clean(artifact_storage)


def test_unsafe_destination_is_rejected(
    publisher, artifact_storage, database, processing_result, tmp_path
):
    outside = tmp_path / "outside"
    outside.mkdir()
    project_id = uuid4()
    (artifact_storage.root / "projects" / str(project_id)).symlink_to(outside)
    with pytest.raises(OSError, match="symlink"):
        publisher.publish_and_complete(
            database, project_id, uuid4(), uuid4(), processing_result
        )
    assert not list(outside.iterdir())
    assert_clean(artifact_storage)


def test_cleanup_failure_does_not_mask_lease_rejection(
    publisher, artifact_storage, database, processing_result, monkeypatch
):
    database.complete_ai_job_with_artifacts.return_value = False

    def denied(path):
        raise PermissionError("cleanup denied")

    monkeypatch.setattr(artifact_storage, "remove_published", denied)
    assert publish(publisher, database, processing_result) is False
    assert len(finals(artifact_storage)) == 2  # Orphans require later reconciliation.


def test_artifact_id_collision_never_overwrites(
    publisher, artifact_storage, database, processing_result, monkeypatch
):
    database.complete_ai_job_with_artifacts.return_value = True
    assert publish(publisher, database, processing_result)
    project_id, _, _, records = database.complete_ai_job_with_artifacts.call_args.args
    files = {path: path.read_bytes() for path in finals(artifact_storage)}
    ids = iter([records[0].id, uuid4()])
    monkeypatch.setattr("intentcut.backend.ai_artifacts.uuid4", lambda: next(ids))
    database.reset_mock()
    with pytest.raises(FileExistsError):
        publisher.publish_and_complete(
            database, project_id, uuid4(), uuid4(), processing_result
        )
    assert {path: path.read_bytes() for path in finals(artifact_storage)} == files
    database.complete_ai_job_with_artifacts.assert_not_called()


def test_non_mp4_video_is_rejected(
    publisher, artifact_storage, database, processing_result, tmp_path
):
    import subprocess

    mkv = tmp_path / "renamed.mp4"
    subprocess.run(
        [
            "ffmpeg",
            "-v",
            "error",
            "-nostdin",
            "-n",
            "-i",
            str(processing_result.staged_video_path),
            "-c",
            "copy",
            "-f",
            "matroska",
            str(mkv),
        ],
        check=True,
        capture_output=True,
        timeout=30,
    )
    with pytest.raises(ValueError, match="valid MP4"):
        publish(
            publisher,
            database,
            ProcessingResult(processing_result.storyboard_path, mkv),
        )
    assert_clean(artifact_storage)


@pytest.mark.parametrize("invalid_index", [0, 1, 2])
def test_destination_identifiers_cannot_contain_paths(
    publisher, artifact_storage, database, processing_result, invalid_index
):
    identifiers = [uuid4(), uuid4(), uuid4()]
    identifiers[invalid_index] = "../../outside"
    with pytest.raises(ValueError, match="UUID ownership"):
        publisher.publish_and_complete(database, *identifiers, processing_result)
    database.complete_ai_job_with_artifacts.assert_not_called()
    assert_clean(artifact_storage)
