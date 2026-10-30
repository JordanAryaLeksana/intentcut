"""Project-scoped caption heads and immutable export snapshots."""

import json
from uuid import UUID

from sqlalchemy import func, select

from intentcut.backend.ai_job_service import AIJobAPIError, AIJobService
from intentcut.backend.artifacts.derived import CAPTION_LIMIT, validate_caption
from intentcut.backend.captions.schemas import (
    PIPELINE,
    CaptionSetResponse,
    CreateCaptions,
    ExportCaptions,
    SaveCaptions,
    SavedCue,
    validate_saved_cues,
)
from intentcut.backend.contracts import PUBLIC_JOB_ERROR_CODES
from intentcut.backend.storage.database_models import (
    AIJob,
    AIJobArtifact,
    CaptionSet,
    Project,
)
from intentcut.backend.transcription.media import verified_video


def conflict() -> AIJobAPIError:
    return AIJobAPIError(
        409, "caption_conflict", "Caption revision changed. Reload before retrying."
    )


class CaptionService:
    def __init__(self, jobs: AIJobService):
        self.jobs, self.database = jobs, jobs.database

    def original(self, project: UUID, identifier: UUID):
        artifact = self.database.get_project_artifact(project, identifier)
        if (
            artifact is None
            or artifact.kind != "captions"
            or artifact.parent_artifact_id is None
        ):
            raise AIJobAPIError(404, "not_found", "Caption transcription not found.")
        with self.jobs.snapshot(project, artifact) as snapshot:
            document = validate_caption(snapshot.read(CAPTION_LIMIT + 1))
        return artifact, document

    @staticmethod
    def response(row: CaptionSet) -> CaptionSetResponse:
        cues = [SavedCue.model_validate(c) for c in row.cues]
        validate_saved_cues(cues, row.duration_ms)
        return CaptionSetResponse(
            id=row.id,
            project_id=row.project_id,
            parent_artifact_id=row.parent_artifact_id,
            parent_sha256=row.parent_sha256,
            transcription_sha256=row.transcription_sha256,
            revision=row.revision,
            duration_ms=row.duration_ms,
            cues=cues,
            updated_at=row.updated_at,
        )

    def get(self, project: UUID, identifier: UUID) -> CaptionSetResponse:
        with self.database._sessions() as session:
            row = session.scalar(
                select(CaptionSet).where(
                    CaptionSet.id == identifier, CaptionSet.project_id == project
                )
            )
            if row is None:
                raise AIJobAPIError(404, "not_found", "Caption set not found.")
            return self.response(row)

    def create(self, project: UUID, body: CreateCaptions) -> CaptionSetResponse:
        original, document = self.original(project, body.transcription_artifact_id)
        # Check the real source version before creating an editable head.
        with verified_video(self.jobs, project, original.parent_artifact_id, 86400) as (
            parent,
            metadata,
            _,
        ):
            if abs(metadata.duration * 1000 - document.duration_ms) > 50:
                raise AIJobAPIError(
                    422, "invalid_captions", "Caption duration does not match video."
                )
            if parent.sha256 != original.parent_sha256:
                raise AIJobAPIError(
                    409, "source_changed", "Caption source version changed."
                )
        cues = [
            SavedCue(
                index=i, start_ms=c.start_ms, end_ms=c.end_ms, text=c.text, enabled=True
            ).model_dump()
            for i, c in enumerate(document.cues)
        ]
        with self.database._sessions.begin() as session:
            session.scalar(
                select(Project).where(Project.id == project).with_for_update()
            )
            row = session.get(CaptionSet, original.id)
            if row is None:
                row = CaptionSet(
                    id=original.id,
                    project_id=project,
                    parent_artifact_id=parent.id,
                    parent_sha256=parent.sha256,
                    transcription_sha256=original.sha256,
                    revision=1,
                    duration_ms=document.duration_ms,
                    cues=cues,
                )
                session.add(row)
                session.flush()
            if row.project_id != project:
                raise AIJobAPIError(404, "not_found", "Caption set not found.")
            return self.response(row)

    def save(
        self, project: UUID, identifier: UUID, body: SaveCaptions
    ) -> CaptionSetResponse:
        original, document = self.original(project, identifier)
        if len(body.cues) != len(document.cues) or any(
            c.index != i for i, c in enumerate(body.cues)
        ):
            raise AIJobAPIError(
                422, "invalid_captions", "Keep all original cue identities and order."
            )
        cues = [
            SavedCue(
                **edit.model_dump(), start_ms=source.start_ms, end_ms=source.end_ms
            ).model_dump()
            for edit, source in zip(body.cues, document.cues, strict=True)
        ]
        if len(json.dumps(cues).encode()) > CAPTION_LIMIT:
            raise AIJobAPIError(
                422, "processing_limit", "Caption set exceeds size limit."
            )
        with self.database._sessions.begin() as session:
            row = session.scalar(
                select(CaptionSet)
                .where(CaptionSet.id == identifier, CaptionSet.project_id == project)
                .with_for_update()
            )
            if row is None:
                raise AIJobAPIError(404, "not_found", "Caption set not found.")
            if row.revision != body.expected_revision:
                raise conflict()
            if row.transcription_sha256 != original.sha256:
                raise AIJobAPIError(
                    409, "source_changed", "Original transcription changed."
                )
            row.cues = cues
            row.revision += 1
            row.updated_at = session.scalar(select(func.clock_timestamp()))
            session.flush()
            return self.response(row)

    def export(self, project: UUID, identifier: UUID, body: ExportCaptions):
        head = self.get(project, identifier)
        with verified_video(self.jobs, project, head.parent_artifact_id, 86400) as (
            parent,
            _,
            _,
        ):
            if parent.sha256 != head.parent_sha256:
                raise AIJobAPIError(409, "source_changed", "Video checksum changed.")
        with self.database._sessions.begin() as session:
            row = session.scalar(
                select(CaptionSet)
                .where(CaptionSet.id == identifier, CaptionSet.project_id == project)
                .with_for_update()
            )
            if row is None or row.revision != body.expected_revision:
                raise conflict()
            existing = session.scalar(
                select(AIJob).where(
                    AIJob.project_id == project,
                    AIJob.request_payload["pipeline_version"].astext == PIPELINE,
                    AIJob.request_payload["caption_set_id"].astext == str(identifier),
                    AIJob.request_payload["caption_revision"].astext
                    == str(row.revision),
                )
            )
            if existing is not None:
                return existing
            snapshot = self.response(row).model_dump(mode="json")
            job = AIJob(
                project_id=project,
                status="queued",
                request_payload={
                    "pipeline_version": PIPELINE,
                    "parent_artifact_id": str(row.parent_artifact_id),
                    "parent_sha256": row.parent_sha256,
                    "caption_set_id": str(row.id),
                    "caption_revision": row.revision,
                    "caption_snapshot": snapshot,
                },
            )
            session.add(job)
            session.flush()
            return job

    def video_state(self, project: UUID, video: UUID):
        parent = self.database.get_project_artifact(project, video)
        if parent is None or parent.kind not in {"video", "rendition"}:
            raise AIJobAPIError(404, "not_found", "Video not found.")
        with self.database._sessions() as session:
            jobs = list(
                session.scalars(
                    select(AIJob)
                    .where(
                        AIJob.project_id == project,
                        AIJob.request_payload["pipeline_version"].astext.in_(
                            [PIPELINE, "caption_transcribe_v1"]
                        ),
                        AIJob.request_payload["parent_artifact_id"].astext
                        == str(video),
                        AIJob.request_payload["parent_sha256"].astext == parent.sha256,
                    )
                    .order_by(AIJob.created_at.desc())
                )
            )
            transcripts = list(
                session.scalars(
                    select(AIJobArtifact)
                    .join(AIJob)
                    .where(
                        AIJob.project_id == project,
                        AIJob.status == "succeeded",
                        AIJobArtifact.kind == "captions",
                        AIJobArtifact.parent_artifact_id == video,
                        AIJobArtifact.parent_sha256 == parent.sha256,
                    )
                )
            )
            heads = list(
                session.scalars(
                    select(CaptionSet)
                    .where(
                        CaptionSet.project_id == project,
                        CaptionSet.parent_artifact_id == video,
                        CaptionSet.parent_sha256 == parent.sha256,
                    )
                    .order_by(CaptionSet.updated_at.desc())
                )
            )
            return {
                "video_artifact_id": video,
                "parent_sha256": parent.sha256,
                "sets": [self.response(h) for h in heads],
                "transcriptions": [
                    {"id": a.id, "job_id": a.job_id} for a in transcripts
                ],
                "jobs": [
                    {
                        "id": j.id,
                        "status": j.status,
                        "error_code": j.error_code
                        if j.error_code in PUBLIC_JOB_ERROR_CODES
                        else ("processing_failed" if j.error_code else None),
                        "enabled_cues": sum(
                            c["enabled"]
                            for c in j.request_payload["caption_snapshot"]["cues"]
                        )
                        if j.request_payload["pipeline_version"] == PIPELINE
                        else None,
                        "kind": j.request_payload["pipeline_version"],
                        "caption_set_id": j.request_payload.get("caption_set_id"),
                        "caption_revision": j.request_payload.get("caption_revision"),
                    }
                    for j in jobs
                ],
            }
