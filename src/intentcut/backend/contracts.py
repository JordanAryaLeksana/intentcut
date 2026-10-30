"""Small processing contracts shared by jobs, first-cut processing and artifacts."""

from dataclasses import dataclass
from pathlib import Path

PUBLIC_JOB_ERROR_CODES = frozenset(
    {
        "processing_failed",
        "unsupported_job_type",
        "unsupported_revision",
        "draft_revision_changed",
        "revision_rejected",
        "worker_lease_expired",
        "processing_limit",
        "source_unavailable",
        "invalid_ai_selection",
        "provider_unavailable",
        "invalid_transcript",
        "invalid_image_output",
        "image_outcome_unknown",
        "image_rate_limited",
        "transcription_outcome_unknown",
        "transcription_rate_limited",
    }
)


class AIProcessingError(Exception):
    """Stable codes only; diagnostics and provider responses stay private."""

    def __init__(self, code: str) -> None:
        if code not in PUBLIC_JOB_ERROR_CODES:
            raise ValueError("Unknown processing error")
        self.code = code
        super().__init__(code)


class JobLeaseLost(RuntimeError):
    """Stop work without attempting an authoritative failure or publication."""


@dataclass(frozen=True)
class ProcessingResult:
    storyboard_path: Path
    staged_video_path: Path


@dataclass(frozen=True)
class ProposalResult:
    proposal: dict
