"""Durable at-most-once provider admission, fenced by the existing job lease."""

from collections.abc import Callable

from sqlalchemy import func, select, update

from intentcut.backend.artifacts.derived import CaptionDocument
from intentcut.backend.contracts import AIProcessingError, JobLeaseLost
from intentcut.backend.shared.persistence_errors import CommitOutcomeUnknown
from intentcut.backend.storage.database import Database
from intentcut.backend.storage.database_models import AIJob

PIPELINE = "caption_transcribe_v1"


def _update_payload(
    database: Database, claimed: AIJob, mutate: Callable[[dict], None]
) -> None:
    commit_attempted = False
    try:
        with database._sessions() as session:
            job = session.scalar(
                select(AIJob)
                .where(
                    AIJob.id == claimed.id,
                    AIJob.project_id == claimed.project_id,
                )
                .with_for_update()
            )
            now = session.scalar(select(func.clock_timestamp()))
            if (
                job is None
                or job.status != "running"
                or job.lease_token != claimed.lease_token
                or job.lease_expires_at is None
                or job.lease_expires_at <= now
            ):
                raise JobLeaseLost("Transcription lease lost")
            if job.request_payload.get("pipeline_version") != PIPELINE:
                raise AIProcessingError("unsupported_job_type")
            payload = dict(job.request_payload)
            mutate(payload)
            updated = session.scalar(
                update(AIJob)
                .where(
                    AIJob.id == job.id,
                    AIJob.status == "running",
                    AIJob.lease_token == claimed.lease_token,
                    AIJob.lease_expires_at > func.clock_timestamp(),
                )
                .values(request_payload=payload)
                .returning(AIJob.id)
            )
            if updated is None:
                raise JobLeaseLost("Transcription lease expired")
            commit_attempted = True
            session.commit()
    except BaseException as exc:
        if commit_attempted:
            raise CommitOutcomeUnknown from exc
        raise


def reserve_provider_call(database: Database, job: AIJob) -> None:
    """Commit BEFORE HTTP. Ambiguity sacrifices a retry, never another paid call."""

    def reserve(payload: dict) -> None:
        if payload.get("voice_call_started") is True:
            raise AIProcessingError("transcription_outcome_unknown")
        payload["voice_call_started"] = True

    _update_payload(database, job, reserve)


def cache_caption(database: Database, job: AIJob, document: CaptionDocument) -> None:
    """Persist only validated public caption fields, never raw provider output."""

    def save(payload: dict) -> None:
        if payload.get("voice_call_started") is not True:
            raise AIProcessingError("processing_failed")
        payload["voice_caption"] = document.model_dump(mode="json", exclude_none=True)

    _update_payload(database, job, save)
