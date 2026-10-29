from dataclasses import dataclass
from math import isfinite

from intentcut.ai.schemas import VideoUnderstandingResult
from intentcut.ai.temporal_windows import TemporalWindow


@dataclass(frozen=True, slots=True)
class WindowEvidence:
    """A subject observed inside a window, not exact scene boundaries."""

    source_media: str
    window_index: int
    window_start_seconds: float
    window_end_seconds: float
    description: str
    editorial_reason: str


def to_window_evidence(
    source_media: str,
    window: TemporalWindow,
    result: VideoUnderstandingResult,
) -> list[WindowEvidence]:
    """Attach known source coordinates to AI-generated descriptions."""

    if not source_media.strip():
        raise ValueError("source_media is required")

    if not (
        isfinite(window.start_seconds)
        and isfinite(window.end_seconds)
        and 0 <= window.start_seconds < window.end_seconds
    ):
        raise ValueError("Invalid source window")

    evidence = []

    for scene in result.scene_candidates:
        if scene.start_seconds is not None or scene.end_seconds is not None:
            raise ValueError("Window analysis requires null scene timestamps")

        evidence.append(
            WindowEvidence(
                source_media=source_media,
                window_index=window.index,
                window_start_seconds=window.start_seconds,
                window_end_seconds=window.end_seconds,
                description=scene.description,
                editorial_reason=scene.editorial_reason,
            )
        )

    return evidence
