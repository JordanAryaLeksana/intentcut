
"""Tests for grounding AI observations to source footage."""

import pytest

from intentcut.ai.schemas import VideoUnderstandingResult
from intentcut.ai.temporal_windows import TemporalWindow
from intentcut.ai.window_analysis import to_window_evidence


def make_result(
    start: float | None = None,
    end: float | None = None,
) -> VideoUnderstandingResult:
    return VideoUnderstandingResult.model_validate(
        {
            "summary": "Workspace video",
            "scene_candidates": [
                {
                    "description": "Monitor showing code",
                    "editorial_reason": "Good reveal",
                    "start_seconds": start,
                    "end_seconds": end,
                }
            ],
        }
    )


def test_maps_observation_to_source_window() -> None:
    evidence = to_window_evidence(
        "clip_b.mp4",
        TemporalWindow(1, 5.0, 10.0),
        make_result(),
    )

    assert len(evidence) == 1
    assert evidence[0].window_index == 1
    assert evidence[0].window_start_seconds == 5.0
    assert evidence[0].window_end_seconds == 10.0
    assert evidence[0].description == "Monitor showing code"


def test_rejects_model_generated_timestamps() -> None:
    with pytest.raises(ValueError, match="null scene timestamps"):
        to_window_evidence(
            "clip_b.mp4",
            TemporalWindow(1, 5.0, 10.0),
            make_result(1.0, 3.0),
        )


def test_rejects_invalid_window() -> None:
    with pytest.raises(ValueError, match="Invalid source window"):
        to_window_evidence(
            "clip_b.mp4",
            TemporalWindow(0, 5.0, 5.0),
            make_result(),
        )


def test_accepts_no_scenes() -> None:
    empty = VideoUnderstandingResult.model_validate(
        {
            "summary": "No useful moments",
            "scene_candidates": [],
        }
    )

    assert (
        to_window_evidence(
            "clip_b.mp4",
            TemporalWindow(0, 0.0, 5.0),
            empty,
        )
        == []
    )
