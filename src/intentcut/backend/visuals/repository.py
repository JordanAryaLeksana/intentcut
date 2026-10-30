"""Lease-fenced provider-call marker and immutable private image cache reference."""

from collections.abc import Callable

from sqlalchemy import func, select, update

from intentcut.backend.contracts import AIProcessingError, JobLeaseLost
from intentcut.backend.shared.persistence_errors import CommitOutcomeUnknown
from intentcut.backend.storage.database import Database
from intentcut.backend.storage.database_models import AIJob
from intentcut.backend.visuals.contracts import PIPELINE


def mutate_payload(
    database: Database, claimed: AIJob, mutate: Callable[[dict], None]
) -> None:
    attempted = False
    try:
        with database._sessions() as session:
            row = session.scalar(
                select(AIJob)
                .where(AIJob.id == claimed.id, AIJob.project_id == claimed.project_id)
                .with_for_update()
            )
            now = session.scalar(select(func.clock_timestamp()))
            if (
                row is None
                or row.status != "running"
                or row.lease_token != claimed.lease_token
                or row.lease_expires_at is None
                or row.lease_expires_at <= now
            ):
                raise JobLeaseLost("Visual job lease lost")
            if row.request_payload.get("pipeline_version") != PIPELINE:
                raise AIProcessingError("unsupported_job_type")
            payload = dict(row.request_payload)
            mutate(payload)
            result = session.scalar(
                update(AIJob)
                .where(
                    AIJob.id == row.id,
                    AIJob.status == "running",
                    AIJob.lease_token == claimed.lease_token,
                    AIJob.lease_expires_at > func.clock_timestamp(),
                )
                .values(request_payload=payload)
                .returning(AIJob.id)
            )
            if result is None:
                raise JobLeaseLost("Visual job lease expired")
            attempted = True
            session.commit()
    except BaseException as exc:
        if attempted:
            raise CommitOutcomeUnknown from exc
        raise


def reserve_call(database: Database, job: AIJob) -> None:
    def reserve(payload):
        if payload.get("image_call_started") is True:
            raise AIProcessingError("image_outcome_unknown")
        payload["image_call_started"] = True

    mutate_payload(database, job, reserve)
