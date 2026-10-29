"""Read actual decoded video frames and verify their CFR output timebase."""

import json
from pathlib import Path

from intentcut.media.models import OutputValidationError
from intentcut.media.process_runner import PROBE_TIMEOUT, ProcessRunner
from intentcut.media.settings import FPS


def measured_frames(path: Path) -> int:
    raw = ProcessRunner().run(
        [
            "ffprobe",
            "-v",
            "error",
            "-select_streams",
            "v:0",
            "-show_frames",
            "-show_entries",
            "frame=best_effort_timestamp_time",
            "-of",
            "json",
            str(path),
        ],
        timeout=PROBE_TIMEOUT,
    )
    frames = json.loads(raw)["frames"]
    if not frames or len(frames) > 120 * FPS:
        raise OutputValidationError("Invalid measured frame count")
    for index, frame in enumerate(frames):
        if abs(float(frame["best_effort_timestamp_time"]) - index / FPS) > 1e-5:
            raise OutputValidationError(
                "Output frame timestamps are not continuous CFR"
            )
    return len(frames)
