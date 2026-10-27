from io import BytesIO
from uuid import uuid4

import pytest

from intentcut.backend.local_media_storage import EmptyFile, FileTooLarge


def test_copy_is_bounded_and_content_is_unchanged(storage):
    class RecordingStream(BytesIO):
        def read(self, size=-1):
            assert 0 < size <= storage.chunk_bytes
            return super().read(size)

    data = b"x" * storage.max_file_bytes
    with storage.staging() as batch:
        staged = storage.stage(RecordingStream(data), batch, uuid4())
        assert staged.size_bytes == len(data)
        assert staged.path.read_bytes() == data
    assert not batch.exists()


@pytest.mark.parametrize(("size", "expected"), [(0, EmptyFile), (2049, FileTooLarge)])
def test_invalid_sizes_clean_staging(storage, size, expected):
    with pytest.raises(expected), storage.staging() as batch:
        storage.stage(BytesIO(b"x" * size), batch, uuid4())
    assert not batch.exists()


def test_publish_uses_server_ids_and_never_overwrites(storage):
    project_id, media_id = uuid4(), uuid4()
    with storage.staging() as batch:
        staged = storage.stage(BytesIO(b"original"), batch, media_id)
        target = storage.publish(staged.path, project_id, media_id)
        assert target == storage.root / storage.storage_key(project_id, media_id)
        with pytest.raises(FileExistsError):
            storage.publish(staged.path, project_id, media_id)
    assert target.read_bytes() == b"original"


def test_refuses_symlink_project_directory(storage, tmp_path):
    project_id = uuid4()
    outside = tmp_path / "outside"
    outside.mkdir()
    (storage.root / "projects" / str(project_id)).symlink_to(outside)
    with storage.staging() as batch:
        staged = storage.stage(BytesIO(b"video"), batch, uuid4())
        with pytest.raises(OSError, match="symlinks"):
            storage.publish(staged.path, project_id, uuid4())
    assert list(outside.iterdir()) == []


def test_publication_failure_removes_only_its_new_directory(storage, monkeypatch):
    project_id, media_id = uuid4(), uuid4()

    def fail(*args):
        raise PermissionError("denied")

    monkeypatch.setattr("intentcut.backend.local_media_storage.os.link", fail)
    with storage.staging() as batch:
        staged = storage.stage(BytesIO(b"video"), batch, media_id)
        with pytest.raises(PermissionError):
            storage.publish(staged.path, project_id, media_id)
    assert not (storage.root / "projects" / str(project_id) / str(media_id)).exists()
