"""Bounded image admission, saved generated history and optimistic cover selection."""

import shutil
from uuid import UUID

from sqlalchemy import select

from intentcut.ai.image import MODEL
from intentcut.backend.ai_job_service import AIJobAPIError, AIJobService
from intentcut.backend.contracts import PUBLIC_JOB_ERROR_CODES
from intentcut.backend.storage.database_models import (
    AIJob,
    AIJobArtifact,
    Project,
    ProjectCover,
)
from intentcut.backend.visuals.contracts import PIPELINE, CoverRequest, VisualRequest
from intentcut.backend.visuals.source import authorized_source


def image_available(settings) -> bool:
    return bool(
        settings
        and settings.image_generation_enabled
        and settings.model_api_key
        and settings.model_api_key.get_secret_value().strip()
        and shutil.which("ffmpeg")
        and shutil.which("ffprobe")
    )


class VisualService:
    def __init__(self, jobs: AIJobService):
        self.jobs, self.database = jobs, jobs.database

    def submit(self, project: UUID, body: VisualRequest):
        settings = self.jobs.settings
        if not image_available(settings):
            raise AIJobAPIError(
                503, "image_unavailable", "Muse Image is not configured."
            )
        parent_hash = None
        if body.source_artifact_id:
            with authorized_source(
                self.jobs, project, body.source_artifact_id, body.frame_seconds
            ) as (parent, _, _):
                parent_hash = parent.sha256
        payload = {
            "pipeline_version": PIPELINE,
            "model": MODEL,
            "prompt": body.prompt.strip(),
            "preset": body.preset,
            "operation": body.operation,
            "parent_artifact_id": str(body.source_artifact_id)
            if body.source_artifact_id
            else None,
            "parent_sha256": parent_hash,
            "frame_seconds": body.frame_seconds,
        }
        with self.database._sessions.begin() as session:
            owner = session.scalar(
                select(Project).where(Project.id == project).with_for_update()
            )
            if owner is None:
                raise AIJobAPIError(404, "not_found", "Project not found.")
            existing = session.get(AIJob, body.request_id)
            if existing:
                if existing.project_id != project:
                    raise AIJobAPIError(404, "not_found", "Request not found.")
                if any(
                    existing.request_payload.get(k) != v for k, v in payload.items()
                ):
                    raise AIJobAPIError(
                        409, "request_conflict", "Request identifier already used."
                    )
                return existing
            prior = list(
                session.scalars(
                    select(AIJob).where(
                        AIJob.project_id == project,
                        AIJob.request_payload["pipeline_version"].astext == PIPELINE,
                    )
                )
            )
            for job in prior:
                if all(job.request_payload.get(k) == v for k, v in payload.items()):
                    return job
            if len(prior) >= settings.image_max_jobs_per_project:
                raise AIJobAPIError(429, "image_limit", "Project image budget reached.")
            if any(j.status in {"queued", "running"} for j in prior):
                raise AIJobAPIError(
                    409, "image_pending", "An image is already processing."
                )
            job = AIJob(
                id=body.request_id,
                project_id=project,
                status="queued",
                request_payload=payload,
            )
            session.add(job)
            session.flush()
            return job

    def history(self, project: UUID):
        with self.database._sessions() as session:
            if session.get(Project, project) is None:
                raise AIJobAPIError(404, "not_found", "Project not found.")
            jobs = list(
                session.scalars(
                    select(AIJob)
                    .where(
                        AIJob.project_id == project,
                        AIJob.request_payload["pipeline_version"].astext == PIPELINE,
                    )
                    .order_by(AIJob.created_at.desc())
                )
            )
            artifacts = list(
                session.scalars(
                    select(AIJobArtifact)
                    .join(AIJob)
                    .where(
                        AIJob.project_id == project,
                        AIJob.status == "succeeded",
                        AIJobArtifact.kind == "image",
                    )
                )
            )
            by_job = {a.job_id: a for a in artifacts}
            cover = session.get(ProjectCover, project)
            return {
                "items": [
                    {
                        "id": j.id,
                        "status": j.status,
                        "error_code": j.error_code
                        if j.error_code in PUBLIC_JOB_ERROR_CODES
                        else ("processing_failed" if j.error_code else None),
                        "preset": j.request_payload["preset"],
                        "operation": j.request_payload["operation"],
                        "model": MODEL,
                        "source_artifact_id": j.request_payload.get(
                            "parent_artifact_id"
                        ),
                        "source_sha256": j.request_payload.get("parent_sha256"),
                        "frame_seconds": j.request_payload.get("frame_seconds"),
                        "artifact_id": by_job[j.id].id if j.id in by_job else None,
                        "size_bytes": by_job[j.id].size_bytes
                        if j.id in by_job
                        else None,
                    }
                    for j in jobs
                ],
                "cover": self.cover_response(cover) if cover else None,
            }

    @staticmethod
    def cover_response(cover):
        return {
            "artifact_id": cover.artifact_id,
            "job_id": cover.job_id,
            "sha256": cover.sha256,
            "revision": cover.revision,
        }

    def set_cover(self, project: UUID, body: CoverRequest):
        artifact = self.database.get_project_artifact(project, body.artifact_id)
        if artifact is None or artifact.kind != "image":
            raise AIJobAPIError(404, "not_found", "Image not found.")
        # Verify immutable actual bytes before recording a persistent selection.
        with self.jobs.snapshot(project, artifact):
            pass
        with self.database._sessions.begin() as session:
            session.scalar(
                select(Project).where(Project.id == project).with_for_update()
            )
            current = session.get(ProjectCover, project)
            if (current.revision if current else 0) != body.expected_revision:
                raise AIJobAPIError(
                    409,
                    "cover_conflict",
                    "Cover changed. Refresh before selecting again.",
                )
            if (
                current
                and current.artifact_id == artifact.id
                and current.sha256 == artifact.sha256
            ):
                return self.cover_response(current)
            if current is None:
                current = ProjectCover(
                    project_id=project,
                    artifact_id=artifact.id,
                    job_id=artifact.job_id,
                    sha256=artifact.sha256,
                    revision=1,
                )
                session.add(current)
            else:
                current.artifact_id, current.job_id, current.sha256 = (
                    artifact.id,
                    artifact.job_id,
                    artifact.sha256,
                )
                current.revision += 1
            session.flush()
            return self.cover_response(current)
