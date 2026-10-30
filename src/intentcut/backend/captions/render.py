"""Plain UTF-8 caption burning: text never enters a filter expression."""

import json
import shutil
import textwrap
from fractions import Fraction
from pathlib import Path

from intentcut.backend.captions.schemas import SavedCue, validate_saved_cues
from intentcut.backend.contracts import AIProcessingError
from intentcut.media.probe_parser import MediaProbe
from intentcut.media.process_runner import PROBE_TIMEOUT, ProcessRunner

FONT = Path("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf")


def frame_info(path: Path) -> tuple[int, Fraction]:
    data = json.loads(
        ProcessRunner().run(
            [
                "ffprobe",
                "-v",
                "error",
                "-select_streams",
                "v:0",
                "-count_frames",
                "-show_entries",
                "stream=nb_read_frames,avg_frame_rate",
                "-of",
                "json",
                str(path),
            ],
            timeout=PROBE_TIMEOUT,
        )
    )["streams"][0]
    return int(data["nb_read_frames"]), Fraction(data["avg_frame_rate"])


def burn_captions(
    source: Path, output: Path, cues: list[SavedCue], duration_ms: int
) -> None:
    validate_saved_cues(cues, duration_ms)
    metadata = MediaProbe().probe(source)
    if (
        abs(metadata.duration * 1000 - duration_ms) > 50
        or abs(metadata.video.start_time) > 0.001
    ):
        raise AIProcessingError("caption_render_unsupported")
    enabled = [c for c in cues if c.enabled]
    if len(enabled) > 200:
        raise AIProcessingError("processing_limit")
    original_frames, original_fps = frame_info(source)
    workspace = output.parent
    if not enabled:
        # An explicit unchanged rendition, not a claim that subtitles were added.
        shutil.copyfile(source, output)
    else:
        if not FONT.is_file():
            raise AIProcessingError("caption_render_unsupported")
        shutil.copyfile(FONT, workspace / "font.ttf")
        fontsize = max(12, metadata.video.height // 26)
        margin = max(8, metadata.video.height // 24)
        width = max(8, int((metadata.video.width - margin * 2) / (fontsize * 0.7)))
        filters = []
        lanes: list[int] = []
        for index, cue in enumerate(enabled):
            # Overlapping speech turns get separate lanes rather than overwrite.
            lane = next(
                (i for i, end in enumerate(lanes) if end <= cue.start_ms), len(lanes)
            )
            if lane == len(lanes):
                lanes.append(cue.end_ms)
            else:
                lanes[lane] = cue.end_ms
            if lane >= 3:
                raise AIProcessingError("processing_limit")
            lines = [
                wrapped
                for line in cue.text.expandtabs(4).split("\n")
                for wrapped in (
                    textwrap.wrap(
                        line, width=width, break_long_words=True, break_on_hyphens=False
                    )
                    or [""]
                )
            ]
            if (
                len(lines) > 4
                or margin * 2 + lane * fontsize * 5 + len(lines) * fontsize * 1.4
                > metadata.video.height
            ):
                raise AIProcessingError("processing_limit")
            name = f"cue_{index:04d}.txt"
            (workspace / name).write_text("\n".join(lines), encoding="utf-8")
            # Every path/expression is server-generated; raw caption text lives
            # only in textfile and expansion=none disables %{...} evaluation.
            filters.append(
                f"drawtext=fontfile=font.ttf:textfile={name}:expansion=none:"
                f"fontsize={fontsize}:fontcolor=white:box=1:boxcolor=black@0.75:boxborderw=6:"
                f"x=(w-text_w)/2:y=h-text_h-{margin + lane * fontsize * 5}:"
                f"enable='gte(t,{cue.start_ms / 1000:.3f})*"
                f"lt(t,{cue.end_ms / 1000:.3f})'"
            )
        script = workspace / "subtitles.filter"
        script.write_text(",".join(filters), encoding="utf-8")
        ProcessRunner().run_ffmpeg(
            [
                "-copyts",
                "-start_at_zero",
                "-i",
                str(source),
                "-map",
                "0:v:0",
                "-map",
                "0:a?",
                "-filter_script:v",
                script.name,
                "-c:v",
                "libx264",
                "-preset",
                "veryfast",
                "-crf",
                "18",
                "-threads",
                "2",
                "-fps_mode",
                "passthrough",
                "-c:a",
                "copy",
                "-map_metadata",
                "-1",
                "-movflags",
                "+faststart",
                "-n",
                str(output),
            ],
            duration=metadata.duration,
            cwd=workspace,
        )
    rendered = MediaProbe().probe(output)
    frames, fps = frame_info(output)
    if (
        frames != original_frames
        or abs(float(fps - original_fps)) > 0.001
        or abs(rendered.duration - metadata.duration)
        > max(0.05, 1 / float(original_fps))
        or bool(metadata.audio) != bool(rendered.audio)
        or (
            metadata.audio
            and (
                metadata.audio.codec,
                metadata.audio.channels,
                metadata.audio.sample_rate,
            )
            != (
                rendered.audio.codec,
                rendered.audio.channels,
                rendered.audio.sample_rate,
            )
        )
    ):
        raise AIProcessingError("processing_failed")
    ProcessRunner().run_ffmpeg(
        ["-i", str(output), "-f", "null", "-"], duration=rendered.duration
    )
