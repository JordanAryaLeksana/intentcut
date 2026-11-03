"""Reopen recovery: project reads and job listing never mutate state."""

from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import Mock
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from intentcut.backend.app import create_app
from intentcut.backend.storage.database import Database, ProjectNotFound
from intentcut.backend.storage.database_models import Project

NOW = datetime(2026, 1, 1, tzinfo=UTC)


def _client(settings, database, storage, probe):
    enabled = settings.model_copy(update={"ai_jobs_local_enabled": True})
    app = create_app(enabled, database=database, storage=storage, probe=probe)
    return TestClient(
        app,
        base_url="http://127.0.0.1:8000",
        client=("127.0.0.1", 12345),
        raise_server_exceptions=False,
    )


def _job(job_id, status):
    return SimpleNamespace(
        id=job_id,
        status=status,
        created_at=NOW,
        updated_at=NOW,
        started_at=None,
        finished_at=None,
        attempt_count=1,
        error_code=None,
        progress=None,
        has_active_lease=False,
        request_payload={"pipeline_version": "uploaded_v1", "secret": "hidden"},
        lease_token=uuid4(),
    )


def test_get_project_returns_the_persisted_row(settings, storage, probe):
    project_id = uuid4()
    database = Mock()
    database.get_project.return_value = Project(
        id=project_id, name="Reopened story", created_at=NOW
    )
    client = _client(settings, database, storage, probe)
    result = client.get(f"/projects/{project_id}")
    assert result.status_code == 200, result.text
    assert result.json() == {
        "id": str(project_id),
        "name": "Reopened story",
        "slug": None,
        "created_at": "2026-01-01T00:00:00Z",
    }
    database.get_project.assert_called_once_with(project_id)
    database.create_project.assert_not_called()


def test_get_project_missing_is_a_definitive_404(settings, storage, probe):
    database = Mock()
    database.get_project.return_value = None
    client = _client(settings, database, storage, probe)
    result = client.get(f"/projects/{uuid4()}")
    assert result.status_code == 404
    assert result.json()["code"] == "not_found"


def test_list_recoverable_is_newest_first_and_read_only(settings, storage, probe):
    project_id, newer, older = uuid4(), uuid4(), uuid4()
    database = Mock()
    database.list_recoverable_ai_jobs.return_value = [
        _job(newer, "succeeded"),
        _job(older, "running"),
    ]
    client = _client(settings, database, storage, probe)
    result = client.get(f"/projects/{project_id}/ai-jobs")
    assert result.status_code == 200, result.text
    items = result.json()["items"]
    assert [item["id"] for item in items] == [str(newer), str(older)]
    assert [item["status"] for item in items] == ["succeeded", "running"]
    # Private request/lease data never reaches the recovery response.
    assert "hidden" not in result.text and "lease" not in result.text
    database.list_recoverable_ai_jobs.assert_called_once_with(project_id)
    database.create_ai_job.assert_not_called()
    database.claim_next_ai_job.assert_not_called()


def test_list_recoverable_empty_and_missing_project(settings, storage, probe):
    database = Mock()
    database.list_recoverable_ai_jobs.return_value = []
    client = _client(settings, database, storage, probe)
    assert client.get(f"/projects/{uuid4()}/ai-jobs").json() == {"items": []}
    database.list_recoverable_ai_jobs.side_effect = ProjectNotFound
    assert client.get(f"/projects/{uuid4()}/ai-jobs").status_code == 404


def test_recoverable_list_limit_is_bounded_before_any_query():
    database = Database(Mock())
    with pytest.raises(ValueError, match="limit"):
        database.list_recoverable_ai_jobs(uuid4(), limit=0)


def test_slugify_and_candidates_are_readable_and_unique_for_duplicate_names():
    from intentcut.backend.projects.slug import (
        is_valid_slug,
        slug_candidates,
        slugify_name,
    )

    assert slugify_name("A Weekend in Motion!") == "a-weekend-in-motion"
    assert slugify_name("Café — Déjà Vu") == "cafe-deja-vu"
    assert slugify_name("!!!") == "project"
    candidates = slug_candidates("My Story")
    assert [next(candidates) for _ in range(3)] == [
        "my-story",
        "my-story-2",
        "my-story-3",
    ]
    long_candidates = slug_candidates("x" * 200)
    assert all(is_valid_slug(next(long_candidates)) for _ in range(5))
    assert not is_valid_slug("Not A Slug") and not is_valid_slug("")


def test_slug_routes_resolve_list_and_404(settings, storage, probe):
    project_id = uuid4()
    database = Mock()
    row = Project(
        id=project_id, name="A Weekend in Motion", created_at=NOW
    )
    row.slug = "a-weekend-in-motion"
    database.get_project_by_slug.return_value = row
    database.list_projects.return_value = [row]
    client = _client(settings, database, storage, probe)
    found = client.get("/projects/by-slug/a-weekend-in-motion")
    assert found.status_code == 200, found.text
    assert found.json()["id"] == str(project_id)
    assert found.json()["slug"] == "a-weekend-in-motion"
    library = client.get("/projects")
    assert [p["slug"] for p in library.json()["items"]] == ["a-weekend-in-motion"]
    database.get_project_by_slug.return_value = None
    assert client.get("/projects/by-slug/missing-story").status_code == 404
    assert client.get("/projects/by-slug/Not_A_Slug").status_code == 404
    database.create_project.assert_not_called()


def test_slug_candidates_stay_valid_unique_and_within_limit():
    from intentcut.backend.projects.slug import is_valid_slug, slug_candidates

    candidates = slug_candidates("x" * 200)
    first_five = [next(candidates) for _ in range(5)]
    assert len(set(first_five)) == 5
    assert all(is_valid_slug(c) and len(c) <= 80 for c in first_five)
    # Duplicate display names never share a slug: the sequence itself
    # is the uniqueness source create_project persists.
    dupes = slug_candidates("Same Name")
    assert [next(dupes) for _ in range(3)] == [
        "same-name",
        "same-name-2",
        "same-name-3",
    ]


def test_slug_migration_is_additive_and_backfills_uniquely():
    from pathlib import Path

    sql = Path("scripts/migrations/007_project_slugs.sql").read_text()
    assert "ADD COLUMN IF NOT EXISTS slug" in sql
    assert "CREATE UNIQUE INDEX IF NOT EXISTS uq_projects_slug" in sql
    assert "left(id::text, 8)" in sql  # duplicate names still unique
    assert "DROP" not in sql and "DELETE" not in sql
