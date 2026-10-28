"""Small processing contracts shared by jobs, first-cut processing and artifacts."""

from dataclasses import dataclass
from pathlib import Path

PUBLIC_JOB_ERROR_CODES = frozenset(
    {
        "processing_failed",
        "worker_lease_expired",
        "processing_limit",
        "source_unavailable",
        "invalid_ai_selection",
        "provider_unavailable",
    }
)


class AIProcessingError(Exception):
    """Stable codes only; diagnostics and provider responses stay private."""

    def __init__(self, code: str) -> None:
        if code not in PUBLIC_JOB_ERROR_CODES:
            raise ValueError("Unknown processing error")
        self.code = code
        super().__init__(code)


@dataclass(frozen=True)
class ProcessingResult:
    storyboard_path: Path
    staged_video_path: Path
