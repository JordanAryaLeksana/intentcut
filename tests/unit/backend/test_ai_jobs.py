
import pytest

from intentcut.backend.jobs.domain import (
    AIJobStatus,
    validate_job_transition,
)


@pytest.mark.parametrize(
    ("current", "target"),
    [
        (AIJobStatus.QUEUED, AIJobStatus.RUNNING),
        (AIJobStatus.QUEUED, AIJobStatus.FAILED),
        (AIJobStatus.RUNNING, AIJobStatus.QUEUED),
        (AIJobStatus.RUNNING, AIJobStatus.SUCCEEDED),
        (AIJobStatus.RUNNING, AIJobStatus.FAILED),
    ],
)
def test_valid_transitions(current, target):
    validate_job_transition(current, target)


@pytest.mark.parametrize(
    ("current", "target"),
    [
        (AIJobStatus.QUEUED, AIJobStatus.SUCCEEDED),
        (AIJobStatus.SUCCEEDED, AIJobStatus.RUNNING),
        (AIJobStatus.FAILED, AIJobStatus.RUNNING),
        (AIJobStatus.RUNNING, AIJobStatus.RUNNING),
        (AIJobStatus.SUCCEEDED, AIJobStatus.FAILED),
    ],
)
def test_invalid_transitions(current, target):
    with pytest.raises(
        ValueError, match="Invalid AI job transition"
    ):
        validate_job_transition(current, target)
