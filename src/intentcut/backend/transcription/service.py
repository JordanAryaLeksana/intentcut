"""Local-only, version-pinned and bounded transcription admission."""

import shutil
from uuid import UUID

from pydantic import BaseModel, ConfigDict
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError

from intentcut.backend.ai_job_service import AIJobAPIError, AIJobService
from intentcut.backend.contracts import AIProcessingError
from intentcut.backend.shared.settings import BackendSettings
from intentcut.backend.storage.database_models import AIJob, Project
from intentcut.backend.transcription.media import verified_video
from intentcut.backend.transcription.repository import PIPELINE
from intentcut.media.models import MediaProcessError


class TranscriptionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    request_id: UUID
    artifact_id: UUID


def transcription_available(settings: BackendSettings) -> bool:
    return bool(
        settings.voice_transcription_enabled
        and settings.model_api_key
        and settings.model_api_key.get_secret_value().strip()
        and shutil.which("ffmpeg")
        and shutil.which("ffprobe")
    )


class TranscriptionService:
    def __init__(self, jobs: AIJobService) -> None:
        self.jobs, self.database = jobs, jobs.database

    def submit(self, project_id: UUID, body: TranscriptionRequest) -> AIJob:
        settings = self.jobs.settings
        if settings is None or not transcription_available(settings):
            raise AIJobAPIError(
                503, "transcription_unavailable", "Transcription is not configured."
            )
        try:
            with verified_video(
                self.jobs,
                project_id,
                body.artifact_id,
                settings.voice_max_duration_seconds,
            ) as (artifact, _, _):
                payload = {
                    "pipeline_version": PIPELINE,
                    "parent_artifact_id": str(artifact.id),
                    "parent_sha256": artifact.sha256,
                }
        except AIProcessingError as exc:
            raise AIJobAPIError(
                422, exc.code, "Video exceeds transcription limits."
            ) from exc
        except (OSError, ValueError, MediaProcessError) as exc:
            raise AIJobAPIError(
                503, "source_unavailable", "Video is unavailable."
            ) from exc
        try:
            with self.database._sessions.begin() as session:
                project = session.scalar(
                    select(Project).where(Project.id == project_id).with_for_update()
                )
                if project is None:
                    raise AIJobAPIError(404, "not_found", "Project not found.")
                existing = session.get(AIJob, body.request_id)
                if existing is not None:
                    if existing.project_id != project_id:
                        raise AIJobAPIError(404, "not_found", "Resource not found.")
                    if any(
                        existing.request_payload.get(key) != value
                        for key, value in payload.items()
                    ):
                        raise AIJobAPIError(
                            409,
                            "request_conflict",
                            "Request identifier was already used.",
                        )
                    return existing
                # Reuse even failed/uncertain jobs for this immutable source. A new
                # browser UUID must not silently pay again for an uncertain result.
                previous = session.scalar(
                    select(AIJob)
                    .where(
                        AIJob.project_id == project_id,
                        AIJob.request_payload["pipeline_version"].astext == PIPELINE,
                        AIJob.request_payload["parent_artifact_id"].astext
                        == str(artifact.id),
                        AIJob.request_payload["parent_sha256"].astext
                        == artifact.sha256,
                    )
                    .order_by(AIJob.created_at)
                    .limit(1)
                )
                if previous is not None:
                    return previous
                count = session.scalar(
                    select(func.count())
                    .select_from(AIJob)
                    .where(
                        AIJob.project_id == project_id,
                        AIJob.request_payload["pipeline_version"].astext == PIPELINE,
                    )
                )
                if count >= settings.voice_max_jobs_per_project:
                    raise AIJobAPIError(
                        429,
                        "transcription_limit",
                        "Project transcription budget reached.",
                    )
                active = session.scalar(
                    select(AIJob.id)
                    .where(
                        AIJob.project_id == project_id,
                        AIJob.request_payload["pipeline_version"].astext == PIPELINE,
                        AIJob.status.in_(["queued", "running"]),
                    )
                    .limit(1)
                )
                if active is not None:
                    raise AIJobAPIError(
                        409,
                        "transcription_pending",
                        "A transcription is already processing.",
                    )
                job = AIJob(
                    id=body.request_id,
                    project_id=project_id,
                    status="queued",
                    request_payload=payload,
                )
                session.add(job)
                session.flush()
                return job
        except IntegrityError as exc:
            raise AIJobAPIError(
                409, "request_conflict", "Request identifier was already used."
            ) from exc
