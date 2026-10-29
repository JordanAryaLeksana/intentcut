
from dataclasses import dataclass
from math import ceil, isfinite


@dataclass(frozen=True, slots=True)
class TemporalWindow:
    index: int
    start_seconds:float
    end_seconds: float

    @property
    def duration_seconds(self)-> float:
        return self.end_seconds - self.start_seconds


def plan_temporal_window(
    duration_seconds:float ,
    *,
    window_seconds: float = 5.0,
    max_windows: int = 12
) -> list[TemporalWindow]:
    if not isfinite(duration_seconds) or duration_seconds <= 0:
        raise ValueError("Video duration must be positive and finite")

    if not isfinite(window_seconds) or window_seconds <= 0:
        raise ValueError("Window size must be positive and finite")

    if (
        isinstance(max_windows, bool)
        or not isinstance(max_windows, int)
        or max_windows < 1
    ):
        raise ValueError("max_windows must be a positive integer")

    if duration_seconds / window_seconds > max_windows:
        raise ValueError("Video exceeds temporal window budget")

    count = ceil(duration_seconds / window_seconds)
    windows= []

    for i in range(count):
        start = i * window_seconds
        end = min(start + window_seconds, duration_seconds)
        windows.append(
            TemporalWindow(
                index=i,
                start_seconds=start,
                end_seconds=end,
            )
        )

    return windows