import shutil
from pathlib import Path

from intentcut.media.models import MediaMetadata, OutputValidationError
from intentcut.media.process import ProcessRunner
from intentcut.media.settings import VIDEO_FILTER


class ClipNormalize:
    def __init__(self, runner: ProcessRunner) -> None:
        self._runner = runner

    def normalize(self, source: MediaMetadata, target: Path, duration: float) -> None:
        """Encode a staged clip to the requested frame-rounded duration in seconds."""
        arguments = ["-n", "-i", str(source.path)]
        if source.audio is None:
            arguments += ["-f", "lavfi", "-i", "anullsrc=r=48000:cl=stereo"]
            audio_map = "1:a:0"
            audio_offset = 0.0
        else:
            audio_map = f"0:{source.audio.index}"
            # Keep a genuine audio delay relative to video, while rebasing both to zero.
            audio_offset = source.audio.start_time - source.video.start_time
        audio_filter = (
            f"asetpts=PTS-STARTPTS+({audio_offset:.9f})/TB,"
            "aresample=48000:async=1:first_pts=0,"
            f"apad,atrim=duration={duration:.9f}"
        )
        arguments += [
            "-map",
            f"0:{source.video.index}",
            "-map",
            audio_map,
            "-map_metadata",
            "-1",
            "-map_chapters",
            "-1",
            "-vf",
            VIDEO_FILTER,
            "-af",
            audio_filter,
            "-c:v",
            "libx264",
            "-preset",
            "veryfast",
            "-crf",
            "20",
            "-pix_fmt",
            "yuv420p",
            "-r",
            "30",
            "-fps_mode",
            "cfr",
            "-bf",
            "0",
            "-threads",
            "2",
            "-video_track_timescale",
            "15360",
            "-c:a",
            "aac",
            "-b:a",
            "192k",
            "-ar",
            "48000",
            "-ac",
            "2",
            "-t",
            f"{duration:.9f}",
            "-movflags",
            "+faststart",
            str(target),
        ]
        self._runner.run_ffmpeg(arguments, duration=duration)


class AudioTimeline:
    def __init__(self, runner: ProcessRunner) -> None:
        self._runner = runner

    def append(self, segment: Path, duration: float, combined: Path) -> None:
        # Decode each MP4 separately so AAC priming/edit lists are respected per clip.
        # Exact PCM sample counts remove end padding before joining the audio timeline.
        samples = round(duration * 48000)
        pcm = segment.with_suffix(".pcm")
        self._runner.run_ffmpeg(
            [
                "-n",
                "-i",
                str(segment),
                "-map",
                "0:a:0",
                "-vn",
                "-af",
                f"apad,atrim=end_sample={samples}",
                "-ar",
                "48000",
                "-ac",
                "2",
                "-c:a",
                "pcm_s16le",
                "-f",
                "s16le",
                str(pcm),
            ],
            duration=duration,
        )
        if pcm.stat().st_size != samples * 2 * 2:
            raise OutputValidationError(
                "Normalized audio has an unexpected sample count."
            )
        with pcm.open("rb") as source, combined.open("ab") as target:
            shutil.copyfileobj(source, target)
        pcm.unlink()


class TimelineMuxer:
    def __init__(self, runner: ProcessRunner) -> None:
        self._runner = runner

    def mux(
        self, manifest: Path, audio_path: Path, target: Path, duration: float
    ) -> None:
        """Combine generated files located together in the staging directory."""
        self._runner.run_ffmpeg(
            [
                "-n",
                "-f",
                "concat",
                "-copyts",
                "-safe",
                "1",
                "-i",
                manifest.name,
                "-f",
                "s16le",
                "-ar",
                "48000",
                "-ac",
                "2",
                "-i",
                audio_path.name,
                "-map",
                "0:v:0",
                "-map",
                "1:a:0",
                "-map_metadata",
                "-1",
                "-map_chapters",
                "-1",
                "-c:v",
                "copy",
                "-c:a",
                "aac",
                "-b:a",
                "192k",
                "-ar",
                "48000",
                "-ac",
                "2",
                "-t",
                f"{duration:.9f}",
                "-movflags",
                "+faststart",
                target.name,
            ],
            duration=duration,
            cwd=target.parent,
        )
