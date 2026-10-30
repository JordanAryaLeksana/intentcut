from dataclasses import replace
from pathlib import Path
from uuid import uuid4

import pytest
from pydantic import ValidationError

from intentcut.ai.story_director import GroundedWindow, StorySelection, build_edit_plan


@pytest.fixture
def windows():
    return [
        GroundedWindow(
            media_id=uuid4(),
            window_index=index,
            source_window_index=0,
            start_seconds=0,
            end_seconds=5,
            render_seconds=5,
            clip=Path(f"private/{index}.mp4"),
            sha256="a" * 64,
            summary="A shot",
            observations=[],
        )
        for index in range(2)
    ]


def selection(indices):
    return StorySelection.model_validate(
        {
            "title": "Story",
            "rationale": "Contrast",
            "selected_windows": [
                {"window_index": index, "reason": "Contrast"} for index in indices
            ],
        }
    )


def test_multi_video_grounding(windows):
    plan = build_edit_plan(
        selection([1, 0]), windows, [w.media_id for w in windows], 10
    )
    assert [cut.media_id for cut in plan.cuts] == [
        w.media_id for w in reversed(windows)
    ]
    assert [cut.playback_order for cut in plan.cuts] == [0, 1]
    assert all(cut.start_seconds == 0 and cut.end_seconds == 5 for cut in plan.cuts)
    assert plan.total_seconds == 10 and plan.render_seconds == 10
    assert "private" not in plan.model_dump_json()


@pytest.mark.parametrize(
    "field,value",
    [
        ("media_id", str(uuid4())),
        ("start_seconds", 1),
        ("source_media", "/private"),
        ("end_seconds", 2),
        ("window_index", True),
        ("window_index", "0"),
    ],
)
def test_model_cannot_choose_ids_paths_or_timestamps(field, value):
    payload = selection([0]).model_dump()
    payload["selected_windows"][0][field] = value
    with pytest.raises(ValidationError):
        StorySelection.model_validate(payload)


@pytest.mark.parametrize("indices", [[0, 0], [-1], []])
def test_duplicate_or_invalid_selections(indices):
    with pytest.raises(ValidationError):
        selection(indices)


@pytest.mark.parametrize("target", [0, -1, float("inf"), float("nan"), 121, 4.9])
def test_invalid_duration_or_overflow(windows, target):
    with pytest.raises(ValueError):
        build_edit_plan(selection([0]), windows, [w.media_id for w in windows], target)


def test_rounding_counts_towards_budget(windows):
    windows[0] = replace(windows[0], render_seconds=5.033333)
    with pytest.raises(ValueError, match="duration budget"):
        build_edit_plan(selection([0]), windows, [w.media_id for w in windows], 5)


def test_unknown_windows_and_ownership(windows):
    with pytest.raises(ValueError, match="Unknown window"):
        build_edit_plan(selection([88]), windows, [w.media_id for w in windows], 10)
    with pytest.raises(ValueError, match="ownership"):
        build_edit_plan(selection([0]), windows, [uuid4()], 10)


def test_invalid_grounded_interval(windows):
    windows[0] = replace(windows[0], end_seconds=float("nan"))
    with pytest.raises(ValueError, match="interval"):
        build_edit_plan(selection([0]), windows, [w.media_id for w in windows], 10)
