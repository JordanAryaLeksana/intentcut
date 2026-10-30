"""Validate identity-only edits against verified immutable published artifacts."""

import json
from typing import Annotated
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import func, select

from intentcut.backend.ai_job_service import AIJobAPIError, AIJobService
from intentcut.backend.artifacts.schemas import PublicStoryboard
from intentcut.backend.storage.database_models import AIJob, EditDraft, Project


class SaveDraft(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expected_revision: int = Field(ge=0, strict=True)
    base_job_id: UUID
    base_artifact_id: UUID
    window_indices: list[Annotated[int, Field(strict=True, ge=0)]] = Field(
        max_length=12
    )


class RenderDraft(BaseModel):
    model_config = ConfigDict(extra="forbid")
    revision: int = Field(gt=0, strict=True)


def conflict() -> AIJobAPIError:
    return AIJobAPIError(
        409,
        "draft_conflict",
        "Draft changed. Reload the saved version before saving again.",
    )


class EditingService:
    def __init__(self, jobs: AIJobService):
        self.jobs = jobs
        self.database = jobs.database

    def resolve(
        self, project_id: UUID, base_job_id: UUID, artifact_id: UUID, indices: list[int]
    ):
        job = self.jobs.get(project_id, base_job_id)
        artifact = self.jobs.artifact(project_id, base_job_id, artifact_id)
        if (
            job.status != "succeeded"
            or job.request_payload.get("pipeline_version") != "uploaded_v1"
            or artifact.kind != "storyboard"
        ):
            raise AIJobAPIError(
                422, "invalid_base", "Choose a completed first-cut storyboard."
            )
        with self.jobs.snapshot(project_id, artifact) as stream:
            storyboard = PublicStoryboard.model_validate(json.load(stream))
        allowed = {cut.window_index: cut for cut in storyboard.cuts}
        if any(type(i) is not int or i not in allowed for i in indices) or len(
            set(indices)
        ) != len(indices):
            raise AIJobAPIError(
                422,
                "invalid_cuts",
                "Cuts must be unique references to the base storyboard.",
            )
        cuts = [allowed[i] for i in indices]
        fingerprints = job.request_payload.get("source_sha256", {})
        for cut in cuts:
            if (
                cut.media_id is None
                or cut.source_window_index is None
                or str(cut.media_id) not in fingerprints
            ):
                raise AIJobAPIError(
                    422, "invalid_source", "Source references are unavailable."
                )
            asset = self.database.get_media(project_id, cut.media_id)
            if cut.end_seconds > asset.duration_seconds + 1e-6:
                raise AIJobAPIError(
                    422, "invalid_source", "Source ranges are unavailable."
                )
        return storyboard, cuts, fingerprints

    def get(self, project_id: UUID):
        self.database.require_project(project_id)
        with self.database._sessions() as session:
            draft = session.get(EditDraft, project_id)
        if draft is None:
            return None
        storyboard, _, _ = self.resolve(
            project_id, draft.base_job_id, draft.base_artifact_id, draft.window_indices
        )
        return self.response(draft, storyboard)

    @staticmethod
    def response(draft: EditDraft, storyboard: PublicStoryboard):
        return {
            "revision": draft.revision,
            "base_job_id": draft.base_job_id,
            "base_artifact_id": draft.base_artifact_id,
            "window_indices": draft.window_indices,
            "updated_at": draft.updated_at,
            "storyboard": storyboard.model_dump(mode="json", exclude_none=True),
        }

    def save(self, project_id: UUID, body: SaveDraft):
        storyboard, _, _ = self.resolve(
            project_id, body.base_job_id, body.base_artifact_id, body.window_indices
        )
        # A project row lock serializes first insert, updates and render admission.
        with self.database._sessions.begin() as session:
            session.scalar(
                select(Project).where(Project.id == project_id).with_for_update()
            )
            current = session.get(EditDraft, project_id)
            if (current.revision if current else 0) != body.expected_revision:
                raise conflict()
            if current is None:
                current = EditDraft(project_id=project_id)
                session.add(current)
            current.base_job_id = body.base_job_id
            current.base_artifact_id = body.base_artifact_id
            current.window_indices = body.window_indices
            current.revision = body.expected_revision + 1
            current.updated_at = session.scalar(select(func.clock_timestamp()))
            session.flush()
            return self.response(current, storyboard)

    def render(self, project_id: UUID, body: RenderDraft):
        saved = self.get(project_id)
        if saved is None or saved["revision"] != body.revision:
            raise conflict()
        storyboard, cuts, fingerprints = self.resolve(
            project_id,
            saved["base_job_id"],
            saved["base_artifact_id"],
            saved["window_indices"],
        )
        if not cuts:
            raise AIJobAPIError(
                422, "empty_draft", "Add at least one cut before rendering."
            )
        payload = {
            "pipeline_version": "manual_v1",
            "draft_revision": body.revision,
            "base_job_id": str(saved["base_job_id"]),
            "base_artifact_id": str(saved["base_artifact_id"]),
            "source_sha256": fingerprints,
            "edit_plan": {
                "title": "Manual sequence",
                "rationale": "Creator edited sequence",
                "target_seconds": storyboard.target_seconds,
                "total_seconds": sum(c.end_seconds - c.start_seconds for c in cuts),
                "render_seconds": 0,
                "cuts": [
                    {
                        **c.model_dump(mode="json", exclude_none=True),
                        "playback_order": i,
                        "editorial_reason": "Creator selected published cut",
                    }
                    for i, c in enumerate(cuts)
                ],
            },
        }
        with self.database._sessions.begin() as session:
            session.scalar(
                select(Project).where(Project.id == project_id).with_for_update()
            )
            current = session.get(EditDraft, project_id)
            if current is None or current.revision != body.revision:
                raise conflict()
            # One immutable render job per revision; retries reuse the same identity.
            job = session.scalar(
                select(AIJob).where(
                    AIJob.project_id == project_id,
                    AIJob.request_payload["pipeline_version"].astext == "manual_v1",
                    AIJob.request_payload["draft_revision"].astext
                    == str(body.revision),
                )
            )
            if job is None:
                job = AIJob(
                    project_id=project_id, request_payload=payload, status="queued"
                )
                session.add(job)
                session.flush()
            elif job.status == "failed":
                job.status = "queued"
                job.error_code = None
                job.progress = None
                job.started_at = None
                job.finished_at = None
                session.flush()
            return job

    def renders(self, project_id: UUID):
        self.database.require_project(project_id)
        with self.database._sessions() as session:
            jobs = session.scalars(
                select(AIJob)
                .where(
                    AIJob.project_id == project_id,
                    AIJob.request_payload["pipeline_version"].astext == "manual_v1",
                )
                .order_by(AIJob.created_at.desc(), AIJob.id.desc())
                .limit(100)
            ).all()
            return [
                {
                    "job_id": j.id,
                    "revision": j.request_payload["draft_revision"],
                    "status": j.status,
                }
                for j in jobs
            ]
