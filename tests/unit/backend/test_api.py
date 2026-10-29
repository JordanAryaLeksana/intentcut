from uuid import uuid4

import pytest
from sqlalchemy.exc import OperationalError

from intentcut.media.models import InvalidMediaError


def test_project_create_validates_and_trims_name(client):
    result = client.post("/projects", json={"name": "  My story  "})
    assert result.status_code == 201
    assert result.json()["name"] == "My story"
    assert set(result.json()) == {"id", "name", "created_at"}


@pytest.mark.parametrize(
    "body", [{"name": " "}, {"name": "a" * 201}, {}, {"name": "ok", "secret": "x"}]
)
def test_invalid_project_body(client, body):
    assert client.post("/projects", json=body).status_code == 422


def test_upload_list_and_scoped_retrieval(client, project, settings):
    path = f"/projects/{project.id}/media"
    result = client.post(
        path,
        files=[("files", ("first.mov", b"one")), ("files", ("second.mp4", b"two"))],
    )
    assert result.status_code == 201, result.text
    items = result.json()["items"]
    assert [item["original_filename"] for item in items] == ["first.mov", "second.mp4"]
    assert items[0]["video"]["frame_rate"] == {"numerator": 24, "denominator": 1}
    assert "storage_key" not in result.text
    assert str(settings.media_root) not in result.text
    assert "private/staged" not in result.text
    listed = client.get(path, params={"limit": 1, "offset": 1})
    assert listed.status_code == 200
    assert len(listed.json()["items"]) == 1
    assert client.get(f"{path}/{items[0]['id']}").json() == items[0]
    assert client.get(f"/projects/{uuid4()}/media/{items[0]['id']}").status_code == 404


def test_missing_project_and_empty_listing(client, project):
    assert client.get(f"/projects/{uuid4()}/media").status_code == 404
    assert (
        client.post(
            f"/projects/{uuid4()}/media", files={"files": ("clip.mp4", b"x")}
        ).status_code
        == 404
    )
    assert client.get(f"/projects/{project.id}/media").json()["items"] == []
    assert client.get("/projects/not-a-uuid/media").status_code == 422
    assert client.get(f"/projects/{project.id}/media?limit=101").status_code == 422


@pytest.mark.parametrize(
    ("filename", "data", "status"),
    [("empty.mp4", b"", 422), ("big.mp4", b"x" * 2049, 413)],
)
def test_invalid_file_size(client, project, filename, data, status):
    result = client.post(
        f"/projects/{project.id}/media", files={"files": (filename, data)}
    )
    assert result.status_code == status, result.text
    assert result.json()["file_index"] == 0


def test_bad_second_file_is_whole_batch_failure(
    client, project, database, probe, metadata, storage
):
    probe.probe.side_effect = [metadata, InvalidMediaError("/secret/path")]
    result = client.post(
        f"/projects/{project.id}/media",
        files=[("files", ("ok.mp4", b"x")), ("files", ("bad.mp4", b"x"))],
    )
    assert result.status_code == 422
    assert result.json()["file_index"] == 1
    assert "secret" not in result.text
    database.save_media_assets.assert_not_called()
    assert not list(storage.root.rglob("original"))


def test_wrong_content_type_and_field_names(client, project):
    path = f"/projects/{project.id}/media"
    assert client.post(path, json={"files": []}).status_code == 415
    assert client.post(path, files={"video": ("a.mp4", b"x")}).status_code == 422
    assert (
        client.post(
            path, data={"unexpected": "value"}, files={"files": ("a.mp4", b"x")}
        ).status_code
        == 400
    )


def test_server_error_does_not_expose_database_diagnostics(client, database):
    database.create_project.side_effect = OperationalError(
        "secret SQL", {}, Exception("secret password")
    )
    result = client.post("/projects", json={"name": "demo"})
    assert result.status_code == 503
    assert "secret" not in result.text


def test_openapi_documents_repeated_multipart_files(client):
    operation = client.get("/openapi.json").json()["paths"][
        "/projects/{project_id}/media"
    ]["post"]
    schema = operation["requestBody"]["content"]["multipart/form-data"]["schema"]
    assert schema["properties"]["files"]["type"] == "array"
    assert schema["properties"]["files"]["maxItems"] == 2
