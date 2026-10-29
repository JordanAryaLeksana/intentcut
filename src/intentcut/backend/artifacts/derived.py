"""Narrow output contracts and bounded local validation; no provider integrations."""

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

from intentcut.media.process_runner import PROBE_TIMEOUT, ProcessRunner

CAPTION_LIMIT = 1024 * 1024
IMAGE_LIMIT = 16 * 1024 * 1024
DERIVED_PIPELINES = {
    "caption_artifact_v1": "captions",
    "caption_transcribe_v1": "captions",
    "image_artifact_v1": "image",
    "video_rendition_v1": "rendition",
}
CONTENT_TYPES = {
    "video": {"video/mp4"},
    "storyboard": {"application/json"},
    "captions": {"application/json"},
    "image": {"image/png", "image/jpeg"},
    "rendition": {"video/mp4"},
}


@dataclass(frozen=True)
class ArtifactParent:
    artifact_id: UUID
    sha256: str

    def __post_init__(self) -> None:
        if (
            not isinstance(self.artifact_id, UUID)
            or not isinstance(self.sha256, str)
            or not re.fullmatch(r"[0-9a-f]{64}", self.sha256)
        ):
            raise ValueError("Invalid parent identity")


@dataclass(frozen=True)
class CaptionArtifactResult:
    path: Path
    parent: ArtifactParent


@dataclass(frozen=True)
class ImageArtifactResult:
    path: Path
    parent: ArtifactParent | None = None


@dataclass(frozen=True)
class VideoRenditionResult:
    path: Path
    parent: ArtifactParent


DerivedResult = CaptionArtifactResult | ImageArtifactResult | VideoRenditionResult
DERIVED_RESULT_TYPES = (
    CaptionArtifactResult,
    ImageArtifactResult,
    VideoRenditionResult,
)


class CaptionCue(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    start_ms: int = Field(ge=0)
    end_ms: int = Field(gt=0)
    text: str = Field(min_length=1, max_length=2000)
    speaker: str | None = Field(default=None, min_length=1, max_length=80)

    @model_validator(mode="after")
    def valid(self) -> "CaptionCue":
        if self.end_ms <= self.start_ms or not self.text.strip():
            raise ValueError("Invalid caption cue")
        return self


class CaptionDocument(BaseModel):
    """Millisecond segment times, never an assertion of word-level precision.

    Empty cues are valid for verified silence. Source lineage lives on the immutable
    artifact row, so a JSON document cannot override its authorized parent.
    """

    model_config = ConfigDict(extra="forbid", strict=True)
    schema_version: Literal["captions-v1"]
    duration_ms: int = Field(gt=0, le=86_400_000)
    cues: list[CaptionCue] = Field(max_length=5000)

    @model_validator(mode="after")
    def valid(self) -> "CaptionDocument":
        previous = -1
        for cue in self.cues:
            if cue.start_ms < previous or cue.end_ms > self.duration_ms:
                raise ValueError("Invalid caption ordering or duration")
            previous = cue.start_ms
        return self


def validate_caption(data: bytes) -> CaptionDocument:
    if not 0 < len(data) <= CAPTION_LIMIT:
        raise ValueError("Invalid caption size")
    return CaptionDocument.model_validate_json(data)


def image_content_type(header: bytes) -> str:
    if header.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if header.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    raise ValueError("Unsupported image format")


def validate_image(path: Path, runner: ProcessRunner) -> str:
    if not 0 < path.stat().st_size <= IMAGE_LIMIT:
        raise ValueError("Invalid image size")
    with path.open("rb") as stream:
        content_type = image_content_type(stream.read(16))
    # Read dimensions before decoding pixels. Only still PNG and JPEG are accepted.
    raw = json.loads(
        runner.run(
            ["ffprobe", "-v", "error", "-show_streams", "-of", "json", str(path)],
            timeout=PROBE_TIMEOUT,
        )
    )
    streams = raw.get("streams", [])
    if len(streams) != 1:
        raise ValueError("Expected one image stream")
    stream = streams[0]
    width, height = stream.get("width", 0), stream.get("height", 0)
    codec = "png" if content_type == "image/png" else "mjpeg"
    if (
        stream.get("codec_name") != codec
        or not 0 < width <= 8192
        or not 0 < height <= 8192
        or width * height > 16_777_216
    ):
        raise ValueError("Invalid image dimensions or codec")
    decoded = json.loads(
        runner.run(
            [
                "ffprobe",
                "-v",
                "error",
                "-count_frames",
                "-show_streams",
                "-of",
                "json",
                str(path),
            ],
            timeout=PROBE_TIMEOUT,
        )
    )
    if decoded["streams"][0].get("nb_read_frames") != "1":
        raise ValueError("Expected a single decoded image")
    runner.run_ffmpeg(["-i", str(path), "-f", "null", "-"], duration=1)
    return content_type
