from math import isfinite

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class SceneCandidate(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    description: str
    editorial_reason: str
    start_seconds: float | None
    end_seconds: float | None

    @field_validator("description", "editorial_reason")
    @classmethod
    def reject_blank_text(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("Scene text must not be blank")
        return value

    @model_validator(mode="after")
    def validate_time_pair(self) -> "SceneCandidate":
        start, end = self.start_seconds, self.end_seconds

        if (start is None) != (end is None):
            raise ValueError(
                "Scene timestamps must be both null or both numeric"
            )

        if start is not None and end is not None:
            if not isfinite(start) or not isfinite(end):
                raise ValueError("Scene timestamps must be finite")

            if start < 0 or end <= start:
                raise ValueError("Scene must have 0 <= start < end")

        return self

class VideoUnderstandingResult(BaseModel):
    """Muse output contract, not a render-ready EditPlan."""

    model_config = ConfigDict(extra="forbid", strict=True)

    summary: str = Field(min_length=1)
    scene_candidates: list[SceneCandidate] = Field(max_length=3)

    @field_validator("summary")
    @classmethod
    def reject_blank_summary(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("Summary must not be blank")
        return value


def validate_scene_bounds(
    result: VideoUnderstandingResult,
    duration: float,
) -> None:
    """Reject timed scenes extending beyond the probed video duration."""

    if not isfinite(duration) or duration <= 0:
        raise ValueError("Video duration must be positive and finite")

    for index, scene in enumerate(result.scene_candidates):
        if scene.end_seconds is not None and scene.end_seconds > duration:
            raise ValueError(
                f"Scene {index} ends beyond video duration"
            )
