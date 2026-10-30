"""Render an immutable saved caption revision without any AI client."""

from uuid import UUID

from intentcut.backend.ai_job_service import AIJobService
from intentcut.backend.artifacts.derived import ArtifactParent, VideoRenditionResult
from intentcut.backend.captions.render import burn_captions
from intentcut.backend.captions.schemas import PIPELINE, CaptionSetResponse
from intentcut.backend.contracts import AIProcessingError, JobLeaseLost
from intentcut.backend.storage.database_models import AIJob
from intentcut.backend.transcription.media import verified_video


class CaptionBurnProcessor:
    def __init__(self, jobs: AIJobService):
        self.jobs = jobs

    def __call__(self, job: AIJob) -> VideoRenditionResult:
        payload = job.request_payload
        if payload.get("pipeline_version") != PIPELINE:
            raise AIProcessingError("unsupported_job_type")
        snapshot = CaptionSetResponse.model_validate(payload["caption_snapshot"])
        if (
            snapshot.project_id != job.project_id
            or str(snapshot.id) != payload["caption_set_id"]
            or snapshot.revision != payload["caption_revision"]
            or str(snapshot.parent_artifact_id) != payload["parent_artifact_id"]
            or snapshot.parent_sha256 != payload["parent_sha256"]
        ):
            raise AIProcessingError("source_unavailable")
        if not self.jobs.database.update_ai_job_progress(
            job.project_id, job.id, job.lease_token, "preparing_media"
        ):
            raise JobLeaseLost("Caption export lease lost")
        with verified_video(
            self.jobs, job.project_id, UUID(payload["parent_artifact_id"]), 86400
        ) as (parent, _, source):
            if parent.sha256 != snapshot.parent_sha256:
                raise AIProcessingError("source_unavailable")
            workspace = self.jobs.storage.job_workspace(
                job.id, job.attempt_count, job.lease_token
            )
            if not self.jobs.database.update_ai_job_progress(
                job.project_id, job.id, job.lease_token, "rendering_video"
            ):
                raise JobLeaseLost("Caption export lease lost")
            output = workspace / "captioned.mp4"
            burn_captions(source, output, snapshot.cues, snapshot.duration_ms)
            return VideoRenditionResult(
                output, ArtifactParent(parent.id, parent.sha256)
            )
