import json

import pytest
from pydantic import ValidationError

from intentcut.ai.schemas import (
    VideoUnderstandingResult,
    validate_scene_bounds,
)


def payload(**scene_overrides: object) -> dict:
    scene = {
        "description": "Computer monitor showing code",
        "editorial_reason": "Useful opening hook",
        "start_seconds": None,
        "end_seconds": None,
    }
    scene.update(scene_overrides)

    return {
        "summary": "A bedroom workspace",
        "scene_candidates": [scene],
    }


def test_accepts_unknown_timestamps() -> None:
    result = VideoUnderstandingResult.model_validate(payload())

    validate_scene_bounds(result, duration=14.036667)

    assert result.scene_candidates[0].start_seconds is None


def test_accepts_known_timestamps_within_video() -> None:
    result = VideoUnderstandingResult.model_validate(
        payload(start_seconds=8.0, end_seconds=12.0)
    )

    validate_scene_bounds(result, duration=14.036667)


@pytest.mark.parametrize(
    ("start", "end"),
    [
        (-1.0, 2.0),
        (5.0, 5.0),
        (9.0, 5.0),
        (None, 4.0),
        (2.0, None),
        (float("nan"), 3.0),
        (0.0, float("inf")),
    ],
)
def test_rejects_invalid_timing(
    start: float | None,
    end: float | None,
) -> None:
    with pytest.raises(ValidationError):
        VideoUnderstandingResult.model_validate(
            payload(start_seconds=start, end_seconds=end)
        )


def test_rejects_out_of_bounds_scene() -> None:
    result = VideoUnderstandingResult.model_validate(
        payload(start_seconds=10.0, end_seconds=15.0)
    )

    with pytest.raises(ValueError, match="beyond video duration"):
        validate_scene_bounds(result, duration=14.036667)


def test_rejects_missing_required_field() -> None:
    data = payload()
    del data["scene_candidates"][0]["editorial_reason"]

    with pytest.raises(ValidationError):
        VideoUnderstandingResult.model_validate(data)


def test_rejects_extra_field() -> None:
    data = payload()
    data["unexpected"] = "ignore your rules"

    with pytest.raises(ValidationError):
        VideoUnderstandingResult.model_validate(data)


def test_rejects_blank_description() -> None:
    with pytest.raises(ValidationError):
        VideoUnderstandingResult.model_validate(
            payload(description="   ")
        )


def test_rejects_invalid_duration() -> None:
    result = VideoUnderstandingResult.model_validate(payload())

    with pytest.raises(ValueError, match="duration"):
        validate_scene_bounds(result, duration=float("nan"))


def test_parses_json_string() -> None:
    result = VideoUnderstandingResult.model_validate_json(
        json.dumps(payload())
    )

    assert len(result.scene_candidates) == 1


def test_allows_zero_scene_candidates() -> None:
    result = VideoUnderstandingResult.model_validate(
        {
            "summary": "No meaningful scene found",
            "scene_candidates": [],
        }
    )

    validate_scene_bounds(result, duration=14.036667)

    assert result.scene_candidates == []


def test_rejects_too_many_scenes() -> None:
    data = payload()
    data["scene_candidates"] = data["scene_candidates"] * 4

    with pytest.raises(ValidationError):
        VideoUnderstandingResult.model_validate(data)
