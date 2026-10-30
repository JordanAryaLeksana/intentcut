"""No Spark calls: verified video -> full WAV -> Voice -> immutable captions."""

from uuid import UUID

from intentcut.ai.voice import MuseVoiceClient
from intentcut.backend.ai_job_service import AIJobAPIError, AIJobService
from intentcut.backend.artifacts.derived import (
    ArtifactParent,
    CaptionArtifactResult,
    CaptionDocument,
)
from intentcut.backend.contracts import AIProcessingError, JobLeaseLost
from intentcut.backend.jobs.progress import ProgressStage
from intentcut.backend.storage.database_models import AIJob
from intentcut.backend.transcription.media import extract_audio, verified_video
from intentcut.backend.transcription.repository import (
    PIPELINE,
    cache_caption,
    reserve_provider_call,
)
from intentcut.media.models import MediaProcessError


class TranscriptionProcessor:
    def __init__(self, jobs: AIJobService, voice: MuseVoiceClient) -> None:
        self.jobs, self.voice = jobs, voice

    def __call__(self, job: AIJob) -> CaptionArtifactResult:
        payload = job.request_payload
        if payload.get("pipeline_version") != PIPELINE:
            raise AIProcessingError("unsupported_job_type")

        def progress(stage: ProgressStage) -> None:
            if not self.jobs.database.update_ai_job_progress(
                job.project_id, job.id, job.lease_token, stage
            ):
                raise JobLeaseLost("Transcription progress fenced")

        progress("preparing_media")
        settings = self.jobs.settings
        if settings is None:
            raise AIProcessingError("processing_failed")
        try:
            parent_id = UUID(payload["parent_artifact_id"])
            with verified_video(
                self.jobs,
                job.project_id,
                parent_id,
                settings.voice_max_duration_seconds,
            ) as (parent, metadata, source):
                if parent.sha256 != payload["parent_sha256"]:
                    raise AIProcessingError("source_unavailable")
                workspace = self.jobs.storage.job_workspace(
                    job.id, job.attempt_count, job.lease_token
                )
                duration_ms = round(metadata.duration * 1000)
                cached = payload.get("voice_caption")
                if cached is not None:
                    try:
                        document = CaptionDocument.model_validate(cached)
                    except ValueError as exc:
                        raise AIProcessingError("invalid_transcript") from exc
                    if document.duration_ms != duration_ms:
                        raise AIProcessingError("invalid_transcript")
                else:
                    if payload.get("voice_call_started") is True:
                        raise AIProcessingError("transcription_outcome_unknown")
                    progress("extracting_audio")
                    wav = workspace / "audio.wav"
                    actual_ms, silent = extract_audio(source, metadata, wav)
                    if silent:
                        # Exact PCM zeros/absent audio: no paid call or invented text.
                        document = CaptionDocument(
                            schema_version="captions-v1",
                            duration_ms=duration_ms,
                            cues=[],
                        )
                    else:
                        progress("transcribing_audio")
                        reserve_provider_call(self.jobs.database, job)
                        document = self.voice.transcribe(wav, job.id, actual_ms)
                        progress("validating_transcript")
                        # Revalidate the document before persisting its public fields.
                        document = CaptionDocument.model_validate(document.model_dump())
                        if document.duration_ms != duration_ms:
                            raise AIProcessingError("invalid_transcript")
                        cache_caption(self.jobs.database, job, document)
                target = workspace / "captions.json"
                target.write_text(
                    document.model_dump_json(exclude_none=True), encoding="utf-8"
                )
                return CaptionArtifactResult(
                    target, ArtifactParent(parent.id, parent.sha256)
                )
        except (AIJobAPIError, OSError, KeyError, ValueError, MediaProcessError) as exc:
            raise AIProcessingError("source_unavailable") from exc
