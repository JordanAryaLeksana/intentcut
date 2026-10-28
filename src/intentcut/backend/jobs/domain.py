"""AI job lifecycle without HTTP, persistence or processor dependencies."""

from enum import StrEnum


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
