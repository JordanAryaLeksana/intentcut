"""Execute media tools with consistent timeouts and domain errors."""

import subprocess
from collections.abc import Sequence
from pathlib import Path

from intentcut.media.models import MediaProcessError, MissingBinaryError

PROBE_TIMEOUT = 30.0


class ProcessRunner:
    @staticmethod
    def render_timeout(duration: float) -> float:
        """Allow slow software encoding, with a five-minute minimum per operation."""
        return max(300.0, duration * 20.0 + 60.0)

    def run(
        self, arguments: Sequence[str], *, timeout: float, cwd: Path | None = None
    ) -> str:
        """Return stdout or translate execution failures into MediaProcessError."""
        try:
            result = subprocess.run(
                list(arguments),
                stdin=subprocess.DEVNULL,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                check=True,
                timeout=timeout,
                cwd=cwd,
            )
        except FileNotFoundError as exc:
            raise MissingBinaryError(
                f"Required executable {arguments[0]!r} was not found; "
                "install it on PATH."
            ) from exc
        except subprocess.TimeoutExpired as exc:
            raise MediaProcessError(
                f"{arguments[0]} timed out after {timeout:.0f} seconds."
            ) from exc
        except subprocess.CalledProcessError as exc:
            detail = (exc.stderr or "No diagnostic output.")[-4000:].strip()
            raise MediaProcessError(
                f"{arguments[0]} failed (exit {exc.returncode}): {detail}"
            ) from exc
        except OSError as exc:
            raise MediaProcessError(f"Cannot run {arguments[0]}: {exc}") from exc
        return result.stdout

    def run_ffmpeg(
        self, arguments: Sequence[str], *, duration: float, cwd: Path | None = None
    ) -> None:
        """Apply common FFmpeg flags and a timeout based on timeline duration."""
        self.run(
            [
                "ffmpeg",
                "-hide_banner",
                "-loglevel",
                "error",
                "-nostdin",
                "-xerror",
                *arguments,
            ],
            timeout=self.render_timeout(duration),
            cwd=cwd,
        )


def render_timeout(duration: float) -> float:
    return ProcessRunner.render_timeout(duration)


def run_process(
    arguments: Sequence[str], *, timeout: float, cwd: Path | None = None
) -> str:
    return ProcessRunner().run(arguments, timeout=timeout, cwd=cwd)


def run_ffmpeg(
    arguments: Sequence[str], *, duration: float, cwd: Path | None = None
) -> None:
    ProcessRunner().run_ffmpeg(arguments, duration=duration, cwd=cwd)
