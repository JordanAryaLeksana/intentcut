from uuid import UUID, uuid4

import pytest
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from intentcut.backend.database import CommitOutcomeUnknown
from intentcut.backend.database_models import MediaAsset
from intentcut.media.probe_parser import MediaProbe

pytestmark = [pytest.mark.integration, pytest.mark.postgres]


def test_multiple_real_videos_are_stored_probed_and_retrievable(
    client, project, database, storage, clip_bytes
):
    path = f"/projects/{project['id']}/media"
    response = client.post(
        path,
        files=[
            ("files", ("../../same.mov", clip_bytes)),
            ("files", ("same.mov", clip_bytes)),
        ],
    )
    assert response.status_code == 201, response.text
    items = response.json()["items"]
    assert len(items) == 2
    assert [item["original_filename"] for item in items] == ["same.mov", "same.mov"]
    assert len({item["id"] for item in items}) == 2
    assert "storage_key" not in response.text
    assert str(storage.root) not in response.text
    for item in items:
        record = database.get_media(UUID(project["id"]), UUID(item["id"]))
        original = storage.root / record.storage_key
        assert original.read_bytes() == clip_bytes
        metadata = MediaProbe().probe(original)
        assert item["duration_seconds"] == pytest.approx(metadata.duration)
        assert item["video"]["width"] == 160
        assert item["audio"] is None
        assert client.get(f"{path}/{item['id']}").json() == item
        assert client.get(f"/projects/{uuid4()}/media/{item['id']}").status_code == 404
    assert len(client.get(path).json()["items"]) == 2
    assert not list((storage.root / ".staging").iterdir())


def test_mixed_valid_corrupt_batch_has_no_rows_or_files(
    client, project, database, storage, clip_bytes
):
    response = client.post(
        f"/projects/{project['id']}/media",
        files=[("files", ("ok.mp4", clip_bytes)), ("files", ("bad.mp4", b"not media"))],
    )
    assert response.status_code == 422, response.text
    assert response.json()["file_index"] == 1
    assert database.list_media(UUID(project["id"]), 100, 0) == []
    assert not list(storage.root.rglob("original"))
    assert not list((storage.root / ".staging").iterdir())


def test_actual_constraint_failure_rolls_back_batch_and_files(
    client, project, database, storage, clip_bytes, monkeypatch
):
    original_save = database.save_media_assets

    def invalid_second(project_id, assets):
        assets[1].size_bytes = 0
        return original_save(project_id, assets)

    monkeypatch.setattr(database, "save_media_assets", invalid_second)
    response = client.post(
        f"/projects/{project['id']}/media",
        files=[("files", ("a.mp4", clip_bytes)), ("files", ("b.mp4", clip_bytes))],
    )
    assert response.status_code == 503
    with Session(database.engine) as session:
        assert session.scalar(select(func.count()).select_from(MediaAsset)) == 0
    assert not list(storage.root.rglob("original"))


def test_lost_commit_ack_reconciles_against_postgresql(
    client, project, database, storage, clip_bytes, monkeypatch
):
    original_save = database.save_media_assets

    def committed_then_disconnected(project_id, assets):
        original_save(project_id, assets)
        raise CommitOutcomeUnknown

    monkeypatch.setattr(database, "save_media_assets", committed_then_disconnected)
    response = client.post(
        f"/projects/{project['id']}/media", files={"files": ("a.mp4", clip_bytes)}
    )
    assert response.status_code == 201, response.text
    assert len(database.list_media(UUID(project["id"]), 100, 0)) == 1
    assert len(list(storage.root.rglob("original"))) == 1


def test_foreign_key_is_enforced_by_postgresql(client, project, database, clip_bytes):
    response = client.post(
        f"/projects/{project['id']}/media", files={"files": ("a.mp4", clip_bytes)}
    )
    media_id = UUID(response.json()["items"][0]["id"])
    with Session(database.engine) as session:
        asset = session.get(MediaAsset, media_id)
        asset.project_id = uuid4()
        with pytest.raises(IntegrityError):
            session.commit()
        session.rollback()
    assert database.get_media(UUID(project["id"]), media_id).project_id == UUID(
        project["id"]
    )


def test_partial_publication_failure_preserves_previous_assets(
    client, project, storage, clip_bytes, monkeypatch
):
    path = f"/projects/{project['id']}/media"
    assert (
        client.post(path, files={"files": ("kept.mp4", clip_bytes)}).status_code == 201
    )
    original_publish = storage.publish
    calls = 0

    def fail_second(*args):
        nonlocal calls
        calls += 1
        if calls == 2:
            raise OSError("disk full")
        return original_publish(*args)

    monkeypatch.setattr(storage, "publish", fail_second)
    response = client.post(
        path, files=[("files", ("a.mp4", clip_bytes)), ("files", ("b.mp4", clip_bytes))]
    )
    assert response.status_code == 500
    assert len(client.get(path).json()["items"]) == 1
    assert len(list(storage.root.rglob("original"))) == 1
