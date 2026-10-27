"""Public response allowlists keep storage paths and probe diagnostics private."""

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

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
