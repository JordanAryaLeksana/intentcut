
"""Regression test: M1A must support a single source video."""

import subprocess
from pathlib import Path

from intentcut.media.render import render_vertical_mp4


def test_single_clip_creates_playable_mp4(tmp_path: Path) -> None:
    source = tmp_path / "source.mp4"
    output = tmp_path / "single_output.mp4"

    # Generate a real video with audio.
    subprocess.run(
        [
            "ffmpeg",
            "-hide_banner",
            "-loglevel",
            "error",
            "-f",
            "lavfi",
            "-i",
            "testsrc2=size=160x90:rate=30",
            "-f",
            "lavfi",
            "-i",
            "sine=frequency=440:sample_rate=48000",
            "-t",
            "1.5",
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
            "-c:a",
            "aac",
            str(source),
        ],
        check=True,
        capture_output=True,
        timeout=60,
    )

    result = render_vertical_mp4([source], output)

    assert result.input_count == 1
    assert output.is_file()
    assert output.stat().st_size > 0
    assert result.metadata.video.width == 720
    assert result.metadata.video.height == 1280
    assert result.metadata.audio is not None

    # Verify complete decoding, not just file existence.
    subprocess.run(
        [
            "ffmpeg",
            "-v",
            "error",
            "-i",
            str(output),
            "-f",
            "null",
            "-",
        ],
        check=True,
        capture_output=True,
        timeout=120,
    )
