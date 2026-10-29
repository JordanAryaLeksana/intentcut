
"""Extract bounded video windows using FFmpeg."""

import subprocess
from math import isfinite
from pathlib import Path


def extract_window(
    source: Path,
    destination: Path,
    *,
    start_seconds: float,
    end_seconds: float,
) -> Path:
    """Extract one timed MP4 segment using video/audio re-encoding."""

    if not source.is_file():
        raise FileNotFoundError(f"Source video not found: {source}")

    if not (
        isfinite(start_seconds)
        and isfinite(end_seconds)
        and 0 <= start_seconds < end_seconds
    ):
        raise ValueError("Invalid temporal window boundaries")

    if destination.suffix.lower() != ".mp4":
        raise ValueError("Destination must be an MP4 file")

    if source.resolve() == destination.resolve():
        raise ValueError("Source and destination must differ")

    if destination.exists():
        raise FileExistsError(destination)

    if not destination.parent.is_dir():
        raise ValueError("Destination directory does not exist")

    duration = end_seconds - start_seconds

    command = [
        "ffmpeg",
        "-hide_banner",
        "-nostdin",
        "-loglevel",
        "error",
        "-ss",
        f"{start_seconds:.6f}",
        "-i",
        str(source),
        "-t",
        f"{duration:.6f}",
        "-map",
        "0:v:0",
        "-map",
        "0:a:0?",
        "-c:v",
        "libx264",
        "-preset",
        "veryfast",
        "-crf",
        "23",
        "-pix_fmt",
        "yuv420p",
        "-c:a",
        "aac",
        "-b:a",
        "128k",
        "-movflags",
        "+faststart",
        "-n",
        str(destination),
    ]

    try:
        subprocess.run(
            command,
            check=True,
            capture_output=True,
            text=True,
            timeout=120,
        )
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as exc:
        destination.unlink(missing_ok=True)
        raise RuntimeError("FFmpeg window extraction failed") from exc

    if not destination.is_file() or destination.stat().st_size == 0:
        destination.unlink(missing_ok=True)
        raise RuntimeError("FFmpeg produced no usable output file")

    return destination
