"""Immutable media data shared across services, plus the public error hierarchy."""

from dataclasses import dataclass
from fractions import Fraction
from pathlib import Path


class MediaError(RuntimeError):
    """Base class for media engine failures."""


class InvalidMediaError(MediaError):
    """An input cannot be used as a finite video clip."""


class MediaProcessError(MediaError):
    """FFmpeg or FFprobe failed or timed out."""


class MissingBinaryError(MediaProcessError):
    """A required executable is unavailable on PATH."""


class OutputValidationError(MediaError):
    """The staged render does not satisfy the output contract."""


@dataclass(frozen=True)
class VideoStream:
    """Selected video stream; rates are exact fractions, timestamps are seconds."""

    index: int
    codec: str
    width: int
    height: int
    pixel_format: str
    frame_rate: Fraction
    nominal_frame_rate: Fraction
    start_time: float


@dataclass(frozen=True)
class AudioStream:
    """Selected audio stream with its original start timestamp in seconds."""

    index: int
    codec: str
    sample_rate: int
    channels: int
    start_time: float


@dataclass(frozen=True)
class MediaMetadata:
    """Usable video duration in seconds and the selected streams for one file."""

    path: Path
    duration: float
    video: VideoStream
    audio: AudioStream | None


@dataclass(frozen=True)
class RenderResult:
    """Published output metadata and the frame-rounded intended timeline duration."""

    output_path: Path
    metadata: MediaMetadata
    input_count: int
    intended_duration: float
    segment_frames: tuple[int, ...] = ()
