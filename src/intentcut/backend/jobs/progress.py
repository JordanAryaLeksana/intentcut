"""Safe, current-attempt progress metadata. No provider payloads or estimated work."""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

ProgressStage = Literal[
    "preparing_media",
    "extracting_windows",
    "extracting_audio",
    "transcribing_audio",
    "validating_transcript",
    "understanding_footage",
    "selecting_story",
    "revising_sequence",
    "rendering_video",
    "publishing_artifacts",
]

STAGES: tuple[ProgressStage, ...] = (
    "preparing_media",
    "extracting_windows",
    "extracting_audio",
    "transcribing_audio",
    "validating_transcript",
    "understanding_footage",
    "selecting_story",
    "revising_sequence",
    "rendering_video",
    "publishing_artifacts",
)


class AIJobProgress(BaseModel):
    model_config = ConfigDict(extra="forbid")

    stage: ProgressStage
    stage_started_at: datetime
    updated_at: datetime
    completed_windows: int | None = Field(default=None, ge=0, strict=True)
    total_windows: int | None = Field(default=None, ge=1, le=12, strict=True)

    @model_validator(mode="after")
    def valid_counts_and_times(self) -> "AIJobProgress":
        if (self.completed_windows is None) != (self.total_windows is None):
            raise ValueError("Window counts must be supplied together")
        if self.total_windows is not None and (
            self.stage != "understanding_footage"
            or self.completed_windows > self.total_windows
        ):
            raise ValueError("Invalid window counts for stage")
        if (
            self.stage_started_at.tzinfo is None
            or self.updated_at.tzinfo is None
            or self.updated_at < self.stage_started_at
        ):
            raise ValueError("Invalid stage timestamps")
        return self
