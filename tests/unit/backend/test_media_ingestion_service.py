import subprocess
from io import BytesIO

import pytest
from sqlalchemy.exc import OperationalError

from intentcut.backend.database import CommitOutcomeUnknown
from intentcut.backend.media_ingestion_service import IngestionError, UploadSource
from intentcut.media.models import (
    InvalidMediaError,
    MediaProcessError,
    MissingBinaryError,
)


def upload(name="clip.mp4", data=b"video"):
    return UploadSource(name, BytesIO(data))


def test_batch_preserves_order_and_sanitizes_names(service, project, storage):
    assets = service.ingest(
        project.id, [upload("../../a.mp4"), upload(r"C:\private\b.mov")]
    )
    assert [asset.original_filename for asset in assets] == ["a.mp4", "b.mov"]
    assert len({asset.id for asset in assets}) == 2
    assert all(
        (storage.root / asset.storage_key).read_bytes() == b"video" for asset in assets
    )
    assert not list((storage.root / ".staging").iterdir())


@pytest.mark.parametrize(
    "failure", [InvalidMediaError("private/path"), PermissionError("disk")]
)
def test_second_file_failure_discards_batch(
    service, database, probe, metadata, project, storage, failure
):
    probe.probe.side_effect = [metadata, failure]
    with pytest.raises((IngestionError, PermissionError)):
        service.ingest(project.id, [upload(), upload()])
    database.save_media_assets.assert_not_called()
    assert not list(storage.root.rglob("original"))
    assert not list((storage.root / ".staging").iterdir())


def test_known_db_failure_removes_only_current_batch(
    service, database, project, storage
):
    accepted = service.ingest(project.id, [upload()])[0]
    database.save_media_assets.side_effect = OperationalError(
        "insert", {}, Exception("database unavailable")
    )
    with pytest.raises(OperationalError):
        service.ingest(project.id, [upload(), upload()])
    assert list(storage.root.rglob("original")) == [storage.root / accepted.storage_key]
    assert not list((storage.root / ".staging").iterdir())


def test_partial_publication_failure_cleans_first_file(
    service, storage, project, monkeypatch
):
    original_publish = storage.publish
    calls = 0

    def publish(*args):
        nonlocal calls
        calls += 1
        if calls == 2:
            raise OSError("disk full")
        return original_publish(*args)

    monkeypatch.setattr(storage, "publish", publish)
    with pytest.raises(OSError):
        service.ingest(project.id, [upload(), upload()])
    assert not list(storage.root.rglob("original"))


def test_uncertain_commit_retains_files_for_reconciliation(
    service, database, project, storage
):
    database.save_media_assets.side_effect = CommitOutcomeUnknown
    with pytest.raises(IngestionError) as error:
        service.ingest(project.id, [upload()])
    assert error.value.code == "commit_uncertain"
    assert len(list(storage.root.rglob("original"))) == 1
    assert not list((storage.root / ".staging").iterdir())


def test_lost_commit_ack_can_return_confirmed_assets(
    service, database, project, storage
):
    save = database.save_media_assets.side_effect

    def commit_then_disconnect(project_id, assets):
        save(project_id, assets)
        raise CommitOutcomeUnknown

    database.save_media_assets.side_effect = commit_then_disconnect
    assets = service.ingest(project.id, [upload(), upload()])
    assert len(assets) == 2
    assert all((storage.root / asset.storage_key).exists() for asset in assets)


@pytest.mark.parametrize(
    "failure", [MissingBinaryError("private executable"), MediaProcessError("timeout")]
)
def test_probe_infrastructure_failure_is_unavailable(service, probe, project, failure):
    probe.probe.side_effect = failure
    with pytest.raises(IngestionError) as error:
        service.ingest(project.id, [upload()])
    assert error.value.code == "probe_unavailable"
    assert "private" not in error.value.message


def test_invalid_file_process_failure_is_client_error(service, probe, project):
    failure = MediaProcessError("diagnostic with private path")
    failure.__cause__ = subprocess.CalledProcessError(1, "ffprobe")
    probe.probe.side_effect = failure
    with pytest.raises(IngestionError) as error:
        service.ingest(project.id, [upload()])
    assert error.value.code == "invalid_media"
    assert error.value.file_index == 0


@pytest.mark.parametrize(
    "uploads", [[], [upload(), upload(), upload()], [upload("../")]]
)
def test_invalid_batch_is_rejected(service, project, database, uploads):
    with pytest.raises(IngestionError):
        service.ingest(project.id, uploads)
    database.save_media_assets.assert_not_called()
