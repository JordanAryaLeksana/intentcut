import math
import os
import tempfile
from collections.abc import Sequence
from dataclasses import replace
from fractions import Fraction
from pathlib import Path

from intentcut.media.frame_manifest import measured_frames
from intentcut.media.models import (
    InvalidMediaError,
    MediaMetadata,
    OutputValidationError,
    RenderResult,
)
from intentcut.media.preprocess_video_pipeline import (
    AudioTimeline,
    ClipNormalize,
    TimelineMuxer,
)
from intentcut.media.probe_parser import MediaProbe
from intentcut.media.process_runner import ProcessRunner
from intentcut.media.settings import FPS


class VerticalVideoRenderer:
    def __init__(
        self,
        runner: ProcessRunner | None = None,
        probe: MediaProbe | None = None,
    ) -> None:
        runner = runner if runner is not None else ProcessRunner()
        self._probe = probe if probe is not None else MediaProbe(runner)
        self._normalizer = ClipNormalize(runner)
        self._audio_timeline = AudioTimeline(runner)
        self._muxer = TimelineMuxer(runner)
        self._validator = OutputValidator(runner)

    def render(
        self,
        input_paths: Sequence[Path],
        output_path: Path,
        *,
        measure_frames: bool = False,
    ) -> RenderResult:
        output_path = self._validate_request(input_paths, output_path)
        sources = [self._probe.probe(Path(path)) for path in input_paths]
        # Round up to a whole video frame; at most one extra frame per source.
        durations = [
            math.ceil(source.duration * FPS - 1e-7) / FPS for source in sources
        ]
        total_duration = sum(durations)

        # Staging beside the destination permits atomic hard-link publication.
        # The context manager removes intermediates on both success and failure.
        frame_counts = [] if measure_frames else None
        with tempfile.TemporaryDirectory(
            prefix=".intentcut-", dir=output_path.parent
        ) as temporary:
            workdir = Path(temporary)
            manifest, audio_path = (
                self._prepare_timeline(sources, durations, workdir, frame_counts)
                if measure_frames
                else self._prepare_timeline(sources, durations, workdir)
            )
            staged = workdir / "render.mp4"
            self._muxer.mux(manifest, audio_path, staged, total_duration)

            metadata = self._probe.probe(staged)
            self._validator.validate(metadata, total_duration)
            self._validator.verify_playback(staged, total_duration)
            if frame_counts is not None and measured_frames(staged) != sum(
                frame_counts
            ):
                raise OutputValidationError(
                    "Rendered frames differ from normalized segments"
                )
            # Fail if another process creates the destination while we render.
            os.link(staged, output_path)

        return RenderResult(
            output_path=output_path,
            metadata=replace(metadata, path=output_path),
            input_count=len(sources),
            intended_duration=total_duration,
            segment_frames=tuple(frame_counts or []),
        )

    @staticmethod
    def _validate_request(input_paths: Sequence[Path], output_path: Path) -> Path:
        if not input_paths:
            raise InvalidMediaError("At least one input videos are required.")
        output_path = Path(output_path).absolute()
        if output_path.exists() or output_path.is_symlink():
            raise FileExistsError(f"Output already exists: {output_path}")
        if output_path.suffix.lower() != ".mp4":
            raise InvalidMediaError("Output filename must have an .mp4 extension.")
        if not output_path.parent.is_dir():
            raise FileNotFoundError(
                f"Output directory does not exist: {output_path.parent}"
            )
        return output_path

    def _prepare_timeline(
        self,
        sources: Sequence[MediaMetadata],
        durations: Sequence[float],
        workdir: Path,
        frame_counts: list[int] | None = None,
    ) -> tuple[Path, Path]:
        entries = ["ffconcat version 1.0"]
        audio_path = workdir / "audio.pcm"
        for index, (source, duration) in enumerate(
            zip(sources, durations, strict=True)
        ):
            segment = workdir / f"segment_{index:06d}.mp4"
            self._normalizer.normalize(source, segment, duration)
            if frame_counts is not None:
                count = measured_frames(segment)
                if count != round(duration * FPS):
                    raise OutputValidationError(
                        "Normalized frame count differs from timeline"
                    )
                frame_counts.append(count)
            self._audio_timeline.append(segment, duration, audio_path)
            # Only generated filenames enter the manifest, never user input paths.
            entries += [f"file '{segment.name}'", f"duration {duration:.9f}"]
        manifest = workdir / "concat.txt"
        manifest.write_text("\n".join(entries) + "\n", encoding="utf-8")
        return manifest, audio_path


def render_vertical_mp4(input_paths: Sequence[Path], output_path: Path) -> RenderResult:
    return VerticalVideoRenderer().render(input_paths, output_path)


def validate_output(metadata: MediaMetadata, intended_duration: float) -> None:
    OutputValidator().validate(metadata, intended_duration)


class OutputValidator:
    """Validate metadata and verify that rendered media is decodable."""

    def __init__(self, runner: ProcessRunner | None = None) -> None:
        self._runner = runner if runner is not None else ProcessRunner()

    def validate(
        self,
        metadata: MediaMetadata,
        intended_duration: float,
    ) -> None:
        """Check that output matches the required video format."""
        video = metadata.video
        audio = metadata.audio
        failures = []

        if (video.codec, video.width, video.height, video.pixel_format) != (
            "h264",
            720,
            1280,
            "yuv420p",
        ):
            failures.append("video must be H.264, 720x1280, yuv420p")

        if video.frame_rate != Fraction(FPS) or video.nominal_frame_rate != Fraction(
            FPS
        ):
            failures.append("video must have average and nominal frame rates of 30 FPS")

        if audio is None or (audio.codec, audio.sample_rate, audio.channels) != (
            "aac",
            48000,
            2,
        ):
            failures.append("audio must be AAC, stereo, 48000 Hz")

        if not math.isfinite(metadata.duration) or metadata.duration <= 0:
            failures.append("duration must be finite and positive")
        elif abs(metadata.duration - intended_duration) > 0.1:
            failures.append("duration differs from the intended timeline by over 0.1s")

        if abs(video.start_time) > 1 / FPS or (
            audio is not None and abs(audio.start_time) > 0.05
        ):
            failures.append("stream timestamps must start near zero")

        if failures:
            raise OutputValidationError(
                "Invalid rendered output: " + "; ".join(failures)
            )

    def verify_playback(self, path: Path, duration: float) -> None:
        """Fully decode video and audio to detect damaged payloads."""
        self._runner.run_ffmpeg(
            ["-i", str(path), "-map", "0:v:0", "-map", "0:a:0", "-f", "null", "-"],
            duration=duration,
        )
