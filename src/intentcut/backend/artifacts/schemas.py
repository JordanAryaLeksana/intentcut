"""Public artifact metadata and sanitized storyboard allowlists."""

from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator


class AIJobArtifactResponse(BaseModel):
    id: UUID
    kind: Literal["video", "storyboard"]
    size_bytes: int
    download_url: str


class AIJobArtifactListResponse(BaseModel):
    items: list[AIJobArtifactResponse]


class PublicStoryboardCut(BaseModel):
    """Numeric allowlist: even prose fields can contain paths or credentials."""

    model_config = ConfigDict(extra="ignore", strict=True)
    window_index: int = Field(ge=0)
    media_id: UUID | None = Field(default=None, strict=False)
    source_window_index: int | None = Field(default=None, ge=0)
    playback_order: int | None = Field(default=None, ge=0)
    start_seconds: float = Field(ge=0, allow_inf_nan=False)
    end_seconds: float = Field(gt=0, allow_inf_nan=False)

    @model_validator(mode="after")
    def valid_range(self) -> "PublicStoryboardCut":
        if self.end_seconds <= self.start_seconds:
            raise ValueError("Invalid cut range")
        return self


class PublicStoryboard(BaseModel):
    model_config = ConfigDict(extra="ignore", strict=True)
    target_seconds: float = Field(gt=0, le=120, allow_inf_nan=False)
    total_seconds: float = Field(gt=0, allow_inf_nan=False)
    render_seconds: float | None = Field(default=None, gt=0, allow_inf_nan=False)
    cuts: list[PublicStoryboardCut] = Field(min_length=1, max_length=12)

    @model_validator(mode="after")
    def valid_timeline(self) -> "PublicStoryboard":
        total = sum(cut.end_seconds - cut.start_seconds for cut in self.cuts)
        if (
            len({cut.window_index for cut in self.cuts}) != len(self.cuts)
            or total > self.target_seconds + 1e-6
            or abs(total - self.total_seconds) > 1e-6
            or (
                self.render_seconds is not None
                and self.render_seconds > self.target_seconds + 1e-6
            )
        ):
            raise ValueError("Invalid timeline")
        return self
