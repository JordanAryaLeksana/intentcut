import pytest

from intentcut.ai.temporal_windows import plan_temporal_window


def test_real_footage_duration() -> None:
    windows = plan_temporal_window(14.036667)

    assert len(windows) == 3
    assert windows[0].start_seconds == 0.0
    assert windows[0].end_seconds == 5.0
    assert windows[1].start_seconds == 5.0
    assert windows[1].end_seconds == 10.0
    assert windows[2].start_seconds == 10.0
    assert windows[2].end_seconds == pytest.approx(14.036667)

def test_short_video() -> None:
    windows = plan_temporal_window(2.0)

    assert len(windows) == 1
    assert windows[0].duration_seconds == 2.0

def test_exact_boundary() -> None:
    windows = plan_temporal_window(10.0)

    assert len(windows) == 2
    assert windows[-1].end_seconds == 10.0

def test_windows_are_contiguous() -> None:
    windows = plan_temporal_window(14.036667)

    for previous, current in zip(windows, windows[1:], strict=False):
        assert previous.end_seconds == current.start_seconds

@pytest.mark.parametrize(
    "duration",
    [0.0, -1.0, float('nan'), float('inf')]
)
def test_invalid_duration(duration:float) -> None:
    with pytest.raises(ValueError):
        plan_temporal_window(duration)

@pytest.mark.parametrize(
    "window_size",
    [0.0, -2.0, float("nan"), float("inf")],
)
def test_invalid_window_sizing(window_size: float) -> None:
    with pytest.raises(ValueError):
        plan_temporal_window(
            10.0,
            window_seconds=window_size,
        )

def test_rejects_six_hour_processing_budget() -> None:
    six_hours = 6 * 60 * 60

    with pytest.raises(ValueError, match="budget"):
        plan_temporal_window(
            six_hours,
            window_seconds=5.0,
            max_windows=12,
        )


def test_rejects_invalid_window_budget() -> None:
    with pytest.raises(ValueError):
        plan_temporal_window(10.0, max_windows=0)
