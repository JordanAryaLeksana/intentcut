"""Immutable worker capabilities and exact routing for persisted pipeline versions."""

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from enum import StrEnum
from types import MappingProxyType

from intentcut.backend.artifacts.derived import (
    DERIVED_RESULT_TYPES,
    CaptionArtifactResult,
    DerivedResult,
    ImageArtifactResult,
    VideoRenditionResult,
)
from intentcut.backend.contracts import (
    AIProcessingError,
    ProcessingResult,
    ProposalResult,
)
from intentcut.backend.storage.database_models import AIJob

JobResult = ProcessingResult | ProposalResult | DerivedResult
JobHandler = Callable[[AIJob], JobResult]
JobResultType = (
    type[ProcessingResult]
    | type[ProposalResult]
    | type[CaptionArtifactResult]
    | type[ImageArtifactResult]
    | type[VideoRenditionResult]
)


class JobType(StrEnum):
    UPLOADED_FIRST_CUT = "uploaded_v1"
    MANUAL_RENDER = "manual_v1"
    SEQUENCE_REVISION = "revision_v1"
    CAPTION_ARTIFACT = "caption_artifact_v1"
    CAPTION_TRANSCRIBE = "caption_transcribe_v1"
    CAPTION_BURN = "caption_burn_v1"
    IMAGE_ARTIFACT = "image_artifact_v1"
    VIDEO_RENDITION = "video_rendition_v1"


_EXPECTED_RESULTS: dict[JobType, JobResultType] = {
    JobType.UPLOADED_FIRST_CUT: ProcessingResult,
    JobType.MANUAL_RENDER: ProcessingResult,
    JobType.SEQUENCE_REVISION: ProposalResult,
    JobType.CAPTION_ARTIFACT: CaptionArtifactResult,
    JobType.CAPTION_TRANSCRIBE: CaptionArtifactResult,
    JobType.CAPTION_BURN: VideoRenditionResult,
    JobType.IMAGE_ARTIFACT: ImageArtifactResult,
    JobType.VIDEO_RENDITION: VideoRenditionResult,
}


@dataclass(frozen=True)
class JobRegistration:
    job_type: JobType
    handler: JobHandler
    result_type: JobResultType


class JobDispatcher:
    """Freeze registrations before polling so claim/recovery and execution agree.

    Future batches add a JobType and an explicit registration. Unregistered types
    are never inferred from payload shape, kind, or a first-cut fallback.
    """

    def __init__(self, registrations: Sequence[JobRegistration]) -> None:
        entries: dict[JobType, JobRegistration] = {}
        for entry in registrations:
            if not isinstance(entry.job_type, JobType):
                raise ValueError("Job registration requires an explicit JobType")
            if entry.job_type in entries:
                raise ValueError("Duplicate job registration")
            if not callable(entry.handler):
                raise ValueError("Job handler must be callable")
            if entry.result_type is not _EXPECTED_RESULTS.get(entry.job_type):
                raise ValueError("Unsupported job result contract")
            entries[entry.job_type] = entry
        if not entries:
            raise ValueError("At least one job registration is required")
        self._registrations = MappingProxyType(entries)

    @property
    def supported_job_types(self) -> tuple[str, ...]:
        return tuple(job_type.value for job_type in self._registrations)

    @property
    def requires_artifact_publisher(self) -> bool:
        return any(
            entry.result_type in (ProcessingResult, *DERIVED_RESULT_TYPES)
            for entry in self._registrations.values()
        )

    def __call__(self, job: AIJob) -> JobResult:
        value = (
            job.request_payload.get("pipeline_version")
            if isinstance(job.request_payload, dict)
            else None
        )
        try:
            job_type = JobType(value) if isinstance(value, str) else None
        except ValueError:
            job_type = None
        registration = self._registrations.get(job_type)
        if registration is None:
            raise AIProcessingError("unsupported_job_type")
        result = registration.handler(job)
        if not isinstance(result, registration.result_type):
            # Prevent a handler's incorrect result reaching the wrong completion
            # path (for example a manual render completing as a proposal).
            raise AIProcessingError("processing_failed")
        return result
