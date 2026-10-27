from uuid import UUID, uuid4

import pytest

pytestmark = [pytest.mark.integration, pytest.mark.postgres]


def test_project_is_committed_and_empty_list_is_scoped(client, database):
    response = client.post("/projects", json={"name": "  Story  "})
    assert response.status_code == 201
    project = response.json()
    assert project["name"] == "Story"
    assert project["created_at"].endswith(("Z", "+00:00"))
    database.require_project(UUID(project["id"]))
    assert client.get(f"/projects/{project['id']}/media").json()["items"] == []
    assert client.get(f"/projects/{uuid4()}/media").status_code == 404


def test_duplicate_project_names_are_allowed(client):
    first = client.post("/projects", json={"name": "Same"}).json()
    second = client.post("/projects", json={"name": "Same"}).json()
    assert first["id"] != second["id"]
