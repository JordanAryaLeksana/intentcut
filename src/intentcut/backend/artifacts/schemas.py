"""Public artifact metadata and sanitized storyboard allowlists."""

from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator


class AIJobArtifactResponse(BaseModel):
    id: UUID
    kind: Literal["video", "storyboard", "captions", "image", "rendition"]
    size_bytes: int
    download_url: str
    content_type: str | None = None
    parent_artifact_id: UUID | None = None
    parent_sha256: str | None = None
    caption_set_id: UUID | None = None
    caption_revision: int | None = None


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


class RenderManifestCut(PublicStoryboardCut):
    output_start_frame: int = Field(ge=0)
    output_end_frame: int = Field(gt=0)


class RenderManifest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    fps: int = Field(ge=30, le=30)
    total_frames: int = Field(gt=0, le=3600)
    draft_revision: int = Field(gt=0)
    base_job_id: UUID = Field(strict=False)
    base_artifact_id: UUID = Field(strict=False)
    cuts: list[RenderManifestCut] = Field(min_length=1, max_length=12)

    @model_validator(mode="after")
    def continuous(self):
        end = 0
        for cut in self.cuts:
            if cut.output_start_frame != end or cut.output_end_frame <= end:
                raise ValueError("Invalid frame boundaries")
            end = cut.output_end_frame
        if end != self.total_frames:
            raise ValueError("Invalid frame total")
        return self


class PublicStoryboard(BaseModel):
    model_config = ConfigDict(extra="ignore", strict=True)
    target_seconds: float = Field(gt=0, le=120, allow_inf_nan=False)
    total_seconds: float = Field(gt=0, allow_inf_nan=False)
    render_manifest: RenderManifest | None = None
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
        if self.render_manifest is not None:
            manifest = self.render_manifest
            if (
                len(manifest.cuts) != len(self.cuts)
                or self.render_seconds is None
                or abs(self.render_seconds - manifest.total_frames / manifest.fps)
                > 1e-6
            ):
                raise ValueError("Manifest duration mismatch")
            for cut, mapped in zip(self.cuts, manifest.cuts, strict=True):
                if (
                    cut.model_dump()
                    != PublicStoryboardCut.model_validate(
                        mapped.model_dump()
                    ).model_dump()
                ):
                    raise ValueError("Manifest source mismatch")
        return self
