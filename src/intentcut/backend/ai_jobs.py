from enum import StrEnum

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


class AIJobStatus(StrEnum):
    QUEUED = "queued"
    FAILED = "failed"
    RUNNING = "running"
    SUCCEEDED = "succeeded"


_ALLOWED_TRANSITIONS = {
    AIJobStatus.QUEUED: frozenset({AIJobStatus.RUNNING, AIJobStatus.FAILED}),
    AIJobStatus.RUNNING: frozenset(
        {
            AIJobStatus.QUEUED,
            AIJobStatus.SUCCEEDED,
            AIJobStatus.FAILED,
        }
    ),
    AIJobStatus.SUCCEEDED: frozenset(),
    AIJobStatus.FAILED: frozenset(),
}


def validate_job_transition(
    current: AIJobStatus,
    target: AIJobStatus,
) -> None:
    """Reject illegal processing state transitions."""

    if target not in _ALLOWED_TRANSITIONS[current]:
        raise ValueError(f"Invalid AI job transition: {current} -> {target}")
