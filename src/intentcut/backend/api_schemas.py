"""Public response allowlists keep storage paths and probe diagnostics private."""

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from intentcut.backend.ai_jobs import AIJobStatus
from intentcut.backend.database_models import MediaAsset, Project


class ProjectCreate(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")
    name: str = Field(min_length=1, max_length=200)


class ProjectResponse(BaseModel):
    id: UUID
    name: str
    created_at: datetime


class FrameRateResponse(BaseModel):
    numerator: int
    denominator: int


class VideoResponse(BaseModel):
    stream_index: int
    codec: str
    width: int
    height: int
    pixel_format: str
    frame_rate: FrameRateResponse


class AudioResponse(BaseModel):
    stream_index: int
    codec: str
    sample_rate: int
    channels: int


class MediaAssetResponse(BaseModel):
    id: UUID
    project_id: UUID
    original_filename: str
    size_bytes: int
    duration_seconds: float
    video: VideoResponse
    audio: AudioResponse | None
    created_at: datetime


class MediaUploadResponse(BaseModel):
    items: list[MediaAssetResponse]


class MediaListResponse(BaseModel):
    items: list[MediaAssetResponse]
    limit: int
    offset: int


class ErrorResponse(BaseModel):
    code: str
    message: str
    file_index: int | None = None


class FirstCutRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    kind: Literal["first_cut"]
    intent: str = Field(min_length=1, max_length=1000)
    target_seconds: float = Field(gt=0, le=120, allow_inf_nan=False, strict=True)
    media_ids: list[UUID] = Field(min_length=1, max_length=10)

    @field_validator("media_ids")
    @classmethod
    def unique_media(cls, value: list[UUID]) -> list[UUID]:
        if len(value) != len(set(value)):
            raise ValueError("Media IDs must be unique")
        return value


class AIJobResponse(BaseModel):
    id: UUID
    status: AIJobStatus
    created_at: datetime
    updated_at: datetime
    started_at: datetime | None
    finished_at: datetime | None
    attempt_count: int
    error_code: str | None


class AIJobAcceptedResponse(BaseModel):
    id: UUID
    status: Literal["queued"]
    status_url: str


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


def project_response(project: Project) -> ProjectResponse:
    return ProjectResponse(
        id=project.id, name=project.name, created_at=project.created_at
    )


def media_response(asset: MediaAsset) -> MediaAssetResponse:
    """Explicit mapping avoids accidental exposure when ORM models gain fields."""
    return MediaAssetResponse(
        id=asset.id,
        project_id=asset.project_id,
        original_filename=asset.original_filename,
        size_bytes=asset.size_bytes,
        duration_seconds=asset.duration_seconds,
        video=VideoResponse(
            stream_index=asset.video_stream_index,
            codec=asset.video_codec,
            width=asset.width,
            height=asset.height,
            pixel_format=asset.pixel_format,
            frame_rate=FrameRateResponse(
                numerator=asset.frame_rate_numerator,
                denominator=asset.frame_rate_denominator,
            ),
        ),
        audio=(
            AudioResponse(
                stream_index=asset.audio_stream_index,
                codec=asset.audio_codec,
                sample_rate=asset.audio_sample_rate,
                channels=asset.audio_channels,
            )
            if asset.audio_stream_index is not None
            else None
        ),
        created_at=asset.created_at,
    )
