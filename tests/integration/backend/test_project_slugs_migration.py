"""Migration 007 on real PostgreSQL: backfill, duplicates, idempotency.

Runs in an isolated schema of the *_test database; development data is
never touched. The pre-migration table is built by hand so the backfill
— not create_all — is what creates and fills the slug column.
"""

import re
from pathlib import Path
from uuid import uuid4

from sqlalchemy import create_engine, text
from sqlalchemy.schema import CreateSchema, DropSchema

MIGRATION = Path("scripts/migrations/007_project_slugs.sql").read_text()
SLUG_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")


def _apply_migration(connection) -> None:
    # psql runs the file as-is; through the driver each statement goes
    # separately so LIKE patterns are never read as placeholders, and
    # semicolons inside the DO block do not split it.
    sql = "\n".join(
        line for line in MIGRATION.splitlines() if not line.lstrip().startswith("--")
    )
    statements, current, in_dollar = [], [], False
    for char in sql:
        current.append(char)
        if "".join(current[-2:]) == "$$":
            in_dollar = not in_dollar
        if char == ";" and not in_dollar:
            statements.append("".join(current))
            current = []
    if "".join(current).strip():
        statements.append("".join(current))
    for statement in statements:
        if statement.strip():
            connection.execute(text(statement))


def test_migration_007_backfills_uniquely_and_is_idempotent(postgres_url):
    schema = f"mig_{uuid4().hex}"
    admin = create_engine(postgres_url, connect_args={"connect_timeout": 5})
    engine = create_engine(
        postgres_url,
        connect_args={"connect_timeout": 5, "options": f"-csearch_path={schema}"},
    )
    try:
        with admin.begin() as connection:
            connection.execute(CreateSchema(schema))
        ids = {}
        with engine.begin() as connection:
            # Pre-007 shape: no slug column at all.
            connection.execute(
                text(
                    "CREATE TABLE projects ("
                    "id UUID PRIMARY KEY, "
                    "name VARCHAR(200) NOT NULL, "
                    "created_at TIMESTAMPTZ NOT NULL DEFAULT now())"
                )
            )
            for key, name in [
                ("dup_a", "My Story"),
                ("dup_b", "My Story"),
                ("accent", "Café — Déjà Vu!"),
                ("empty", "!!!"),
                ("spaced", "  Spaced  Name  "),
            ]:
                row_id = uuid4()
                ids[key] = (row_id, name)
                connection.execute(
                    text("INSERT INTO projects (id, name) VALUES (:id, :name)"),
                    {"id": row_id, "name": name},
                )
            _apply_migration(connection)
            rows = {
                str(r.id): r
                for r in connection.execute(
                    text("SELECT id, name, slug FROM projects")
                )
            }
            # Every row backfilled, unique, readable; identity untouched.
            assert len(rows) == 5
            slugs = [r.slug for r in rows.values()]
            assert all(s and SLUG_RE.fullmatch(s) for s in slugs)
            assert len(set(slugs)) == 5
            for row_id, name in ids.values():
                assert rows[str(row_id)].name == name
            assert rows[str(ids["dup_a"][0])].slug != rows[str(ids["dup_b"][0])].slug
            assert rows[str(ids["accent"][0])].slug.startswith("cafe-deja-vu-")
            assert rows[str(ids["empty"][0])].slug.startswith("project-")
            first = {k: r.slug for k, r in rows.items()}
            # Second application changes nothing.
            _apply_migration(connection)
            again = {
                str(r.id): r.slug
                for r in connection.execute(text("SELECT id, slug FROM projects"))
            }
            assert again == first
    finally:
        engine.dispose()
        with admin.begin() as connection:
            connection.execute(DropSchema(schema, cascade=True))
        admin.dispose()


def test_duplicate_names_persist_distinct_slugs(database):
    first = database.create_project("Same Name")
    second = database.create_project("Same Name")
    assert first.slug == "same-name"
    assert second.slug == "same-name-2"
    assert database.get_project_by_slug("same-name").id == first.id
    assert database.get_project_by_slug("same-name-2").id == second.id
    assert database.get_project_by_slug("missing-story") is None
    assert [p.id for p in database.list_projects()] == [second.id, first.id]
