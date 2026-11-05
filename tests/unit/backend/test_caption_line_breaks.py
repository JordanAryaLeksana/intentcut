"""Multi-line captions must not burn a missing-glyph box at line breaks.

Regression for the exported caption defect: FFmpeg drawtext (observed with
8.0) breaks a line on a literal LF inside ``textfile`` but also draws the font's
.notdef box for it. The renderer now draws each wrapped line separately, so no
line-break character reaches FFmpeg. Uses a synthetic local fixture and real
FFmpeg; no transcription or other provider is involved.
"""

import shutil
import subprocess
from pathlib import Path

import pytest

import intentcut.backend.captions.render as renderer
from intentcut.backend.captions.schemas import SavedCue

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        not shutil.which("ffmpeg") or not renderer.FONT.is_file(),
        reason="requires FFmpeg and the DejaVu caption font",
    ),
]

WIDTH, HEIGHT, BACKGROUND = 720, 1280, 0x80


def _ffmpeg(*args: str) -> bytes:
    return subprocess.run(
        ["ffmpeg", "-v", "error", "-nostdin", "-y", *args],
        check=True,
        capture_output=True,
        timeout=120,
    ).stdout


def _gray_frame(video_or_filter: list[str]) -> bytes:
    frame = _ffmpeg(
        *video_or_filter, "-frames:v", "1", "-f", "rawvideo", "-pix_fmt", "gray", "-"
    )
    assert len(frame) == WIDTH * HEIGHT
    return frame


def _caption_extent(frame: bytes) -> tuple[int, int, int]:
    """(widest drawn width, first row, last row) of pixels that differ from bg."""
    widest, rows = 0, []
    for y in range(HEIGHT):
        row = frame[y * WIDTH : (y + 1) * WIDTH]
        drawn = [x for x, value in enumerate(row) if abs(value - BACKGROUND) > 40]
        if drawn:
            rows.append(y)
            widest = max(widest, drawn[-1] - drawn[0] + 1)
    return widest, rows[0] if rows else -1, rows[-1] if rows else -1


@pytest.fixture
def source(tmp_path: Path) -> Path:
    path = tmp_path / "source.mp4"
    _ffmpeg(
        "-f", "lavfi", "-i", f"color=c=0x808080:s={WIDTH}x{HEIGHT}:r=24:d=2",
        "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p",
        "-color_range", "pc", str(path),
    )  # fmt: skip
    return path


def _reference_line_width(tmp_path: Path, text: str, fontsize: int) -> int:
    """Width of one line drawn alone, the known-good (newline-free) oracle."""
    tmp_path.mkdir(exist_ok=True)
    shutil.copyfile(renderer.FONT, tmp_path / "font.ttf")
    (tmp_path / "line.txt").write_text(text, encoding="utf-8")
    frame = _gray_frame(
        [
            "-f", "lavfi", "-i", f"color=c=0x808080:s={WIDTH}x{HEIGHT}:r=24:d=1",
            "-vf",
            f"drawtext=fontfile={tmp_path / 'font.ttf'}:"
            f"textfile={tmp_path / 'line.txt'}:"
            f"expansion=none:fontsize={fontsize}:fontcolor=white:box=1:"
            "boxcolor=black@0.75:boxborderw=6:x=(w-text_w)/2:y=600",
        ]
    )  # fmt: skip
    return _caption_extent(frame)[0]


def test_two_line_caption_burns_both_lines_without_line_break_glyph(
    tmp_path: Path, source: Path
):
    job = tmp_path / "job"
    job.mkdir()
    output = job / "captioned.mp4"
    cue = SavedCue(
        index=0, start_ms=0, end_ms=2000, text="Tapi aku harus\nmakan sih", enabled=True
    )

    renderer.burn_captions(source, output, [cue], 2000)

    # No textfile handed to FFmpeg contains a line-break character.
    texts = sorted(job.glob("cue_*.txt"))
    contents = [path.read_text(encoding="utf-8") for path in texts]
    assert contents == ["Tapi aku harus", "makan sih"]
    assert not any("\n" in text or "\r" in text for text in contents)

    fontsize = max(12, HEIGHT // 26)
    expected = _reference_line_width(tmp_path / "ref", "Tapi aku harus", fontsize)
    widest, top, bottom = _caption_extent(_gray_frame(["-ss", "1", "-i", str(output)]))
    # A .notdef box after "harus" would widen the first line by a glyph advance
    # (~0.6 em ≈ 29px at this size); allow only encoder edge noise.
    assert abs(widest - expected) <= 4, (widest, expected)
    # Both lines are drawn: the caption block is taller than one line box.
    assert bottom - top > fontsize * 1.6
    # The block sits inside the frame, above the bottom margin.
    assert bottom < HEIGHT - max(8, HEIGHT // 24) + fontsize


def test_blank_line_keeps_its_space_but_writes_no_empty_textfile(
    tmp_path: Path, source: Path
):
    job = tmp_path / "job"
    job.mkdir()
    cue = SavedCue(index=0, start_ms=0, end_ms=2000, text="Atas\n\nBawah", enabled=True)
    renderer.burn_captions(source, job / "captioned.mp4", [cue], 2000)
    files = sorted(job.glob("cue_*.txt"))
    # drawtext rejects an empty textfile; the blank middle line is skipped.
    assert [path.name for path in files] == ["cue_0000_00.txt", "cue_0000_02.txt"]
    script = (job / "subtitles.filter").read_text(encoding="utf-8")
    assert script.count("drawtext=") == 2
