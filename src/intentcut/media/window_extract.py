
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
    video_stream_index: int | None = None,
    audio_stream_index: int | None = None,
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

    if destination.exists() or destination.is_symlink():
        raise FileExistsError(destination)

    if not destination.parent.is_dir():
        raise ValueError("Destination directory does not exist")

    duration = end_seconds - start_seconds
    for index in (video_stream_index, audio_stream_index):
        if index is not None and (type(index) is not int or index < 0):
            raise ValueError("Invalid stream index")
    maps = ["-map", "0:v:0", "-map", "0:a:0?"]
    if video_stream_index is not None:
        maps = ["-map", f"0:{video_stream_index}"]
        if audio_stream_index is not None:
            maps += ["-map", f"0:{audio_stream_index}"]

    command = [
        "ffmpeg",
        "-hide_banner",
        "-nostdin",
        "-loglevel",
        "error",
        "-xerror",
        "-ss",
        f"{start_seconds:.6f}",
        "-i",
        str(source),
        "-t",
        f"{duration:.6f}",
        *maps,
        "-c:v",
        "libx264",
        "-preset",
        "veryfast",
        "-crf",
        "23",
        "-threads",
        "2",
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
