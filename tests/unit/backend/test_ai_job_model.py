from sqlalchemy import CheckConstraint
from sqlalchemy.dialects.postgresql import JSONB

from intentcut.backend.ai_jobs import AIJobStatus
from intentcut.backend.database_models import AIJob, Base


def test_ai_jobs_registered_in_metadata() -> None:
    assert "ai_jobs" in Base.metadata.tables


def test_ai_job_project_foreign_key() -> None:
    table = AIJob.__table__

    targets = {
        foreign_key.target_fullname
        for foreign_key in table.c.project_id.foreign_keys
    }

    assert targets == {"projects.id"}
    assert table.c.project_id.nullable is False


def test_ai_job_status_default() -> None:
    column = AIJob.__table__.c.status

    assert column.default.arg == AIJobStatus.QUEUED.value
    assert column.nullable is False


def test_ai_job_uses_postgresql_jsonb() -> None:
    column = AIJob.__table__.c.request_payload

    assert isinstance(column.type, JSONB)
    assert column.nullable is False


def test_ai_job_has_database_constraints() -> None:
    constraints = {
        constraint.name
        for constraint in AIJob.__table__.constraints
        if isinstance(constraint, CheckConstraint)
    }

    assert "ai_job_valid_status" in constraints
    assert "ai_job_payload_object" in constraints

def test_ai_job_lease_columns() -> None:
    table = AIJob.__table__

    assert table.c.lease_token.nullable
    assert table.c.lease_expires_at.nullable
    assert not table.c.attempt_count.nullable
    assert table.c.attempt_count.server_default.arg == "0"