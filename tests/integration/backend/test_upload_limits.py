import pytest

pytestmark = [pytest.mark.integration, pytest.mark.postgres]


def test_limit_failures_never_leave_assets(
    client, project, storage, settings, clip_bytes
):
    path = f"/projects/{project['id']}/media"
    too_many = [("files", ("a.mp4", clip_bytes))] * (settings.max_upload_files + 1)
    assert client.post(path, files=too_many).status_code == 413
    assert client.post(path, files={"files": ("empty.mp4", b"")}).status_code == 422
    assert (
        client.post(
            path, files={"files": ("large.mp4", b"x" * (settings.max_file_bytes + 1))}
        ).status_code
        == 413
    )
    assert client.get(path).json()["items"] == []
    assert not list(storage.root.rglob("original"))
    assert not list((storage.root / ".staging").iterdir())
