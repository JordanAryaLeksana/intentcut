"""Read local media metadata and interpret FFprobe JSON."""

import json
import math
from fractions import Fraction
from pathlib import Path
from typing import Any

from intentcut.media.models import (
    AudioStream,
    InvalidMediaError,
    MediaMetadata,
    VideoStream,
)
from intentcut.media.process import PROBE_TIMEOUT, ProcessRunner


class ProbeParser:
    """Convert FFprobe JSON into immutable models using stream-order selection."""

    def parse(self, raw: str, path: Path) -> MediaMetadata:
        """Select the first real video and first audio stream in stream order."""
        try:
            data = json.loads(raw)
            streams = data["streams"]
            video = next(
                (
                    stream
                    for stream in streams
                    if stream.get("codec_type") == "video"
                    and not stream.get("disposition", {}).get("attached_pic", 0)
                ),
                None,
            )
            if video is None:
                raise ValueError("No usable video stream")
            audio = next(
                (stream for stream in streams if stream.get("codec_type") == "audio"),
                None,
            )
            width, height = int(video["width"]), int(video["height"])
            if min(width, height) <= 0:
                raise ValueError("Video dimensions must be positive")
            metadata = MediaMetadata(
                path=path,
                duration=self._resolve_duration(video, data.get("format", {})),
                video=VideoStream(
                    index=int(video["index"]),
                    codec=str(video.get("codec_name", "")),
                    width=width,
                    height=height,
                    pixel_format=str(video.get("pix_fmt", "")),
                    frame_rate=self._parse_frame_rate(video.get("avg_frame_rate")),
                    nominal_frame_rate=self._parse_frame_rate(
                        video.get("r_frame_rate")
                    ),
                    start_time=self._parse_start_time(video),
                ),
                audio=(
                    AudioStream(
                        index=int(audio["index"]),
                        codec=str(audio.get("codec_name", "")),
                        sample_rate=int(audio.get("sample_rate", 0)),
                        channels=int(audio.get("channels", 0)),
                        start_time=self._parse_start_time(audio),
                    )
                    if audio is not None
                    else None
                ),
            )
        except (ValueError, TypeError, KeyError, AttributeError, OverflowError) as exc:
            raise InvalidMediaError(
                f"Invalid media metadata for {path}: {exc}"
            ) from exc
        return metadata

    @staticmethod
    def _parse_frame_rate(value: Any) -> Fraction:
        try:
            rate = Fraction(str(value))
            return rate if rate > 0 else Fraction(0)
        except (ValueError, ZeroDivisionError):
            return Fraction(0)

    @staticmethod
    def _parse_start_time(stream: dict[str, Any]) -> float:
        try:
            value = float(stream.get("start_time", 0))
        except (TypeError, ValueError):
            return 0.0
        return value if math.isfinite(value) else 0.0

    def _resolve_duration(
        self, video: dict[str, Any], container: dict[str, Any]
    ) -> float:
        value = video.get("duration")
        if value in (None, "N/A"):
            ticks = video.get("duration_ts")
            time_base = self._parse_frame_rate(video.get("time_base"))
            if ticks not in (None, "N/A") and time_base:
                value = float(ticks) * float(time_base)
            else:
                value = container.get("duration")
        duration = float(value)
        if not math.isfinite(duration) or duration <= 0:
            raise ValueError("Video duration must be finite and positive")
        return duration


class MediaProbe:
    """Check input files, run FFprobe, and delegate metadata parsing."""

    def __init__(
        self,
        runner: ProcessRunner | None = None,
        parser: ProbeParser | None = None,
    ) -> None:
        self._runner = runner if runner is not None else ProcessRunner()
        self._parser = parser if parser is not None else ProbeParser()

    def probe(self, path: Path) -> MediaMetadata:
        """Inspect a regular local file and return its selected stream metadata."""
        path = Path(path).absolute()
        if not path.is_file():
            raise InvalidMediaError(
                f"Input is missing or is not a regular file: {path}"
            )
        raw = self._runner.run(
            [
                "ffprobe",
                "-v",
                "error",
                "-show_streams",
                "-show_format",
                "-of",
                "json",
                str(path),
            ],
            timeout=PROBE_TIMEOUT,
        )
        return self._parser.parse(raw, path)


def parse_probe_json(raw: str, path: Path) -> MediaMetadata:
    """Compatibility entry point; see :meth:`ProbeParser.parse`."""
    return ProbeParser().parse(raw, path)


def probe_media(path: Path) -> MediaMetadata:
    """Compatibility entry point; see :meth:`MediaProbe.probe`."""
    return MediaProbe().probe(path)
