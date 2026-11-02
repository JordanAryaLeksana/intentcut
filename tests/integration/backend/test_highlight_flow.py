"""LOCAL_INTEGRATION: real FFmpeg discovery, extraction, render, validation.

No provider calls, no database. A synthetic source stands in for long-form
footage; duration arithmetic at six hours is covered by unit tests.
"""

import subprocess
from pathlib import Path
from uuid import uuid4

import pytest

from intentcut.ai.story_director import (
    GroundedWindow,
    StorySelection,
    build_edit_plan,
)
from intentcut.backend.highlights import discovery
from intentcut.backend.highlights.discovery import ffmpeg_probe
from intentcut.media.probe_parser import MediaProbe
from intentcut.media.render import render_vertical_mp4
from intentcut.media.window_extract import extract_window


def make_source(path: Path, seconds: float = 24.0) -> None:
    subprocess.run(
        [
            "ffmpeg",
            "-hide_banner",
            "-loglevel",
            "error",
            "-f",
            "lavfi",
            "-i",
            "testsrc2=size=320x180:rate=30",
            "-f",
            "lavfi",
            "-i",
            "sine=frequency=440:sample_rate=48000",
            "-t",
            str(seconds),
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
            "-c:a",
            "aac",
            "-shortest",
            str(path),
        ],
        check=True,
        capture_output=True,
        timeout=120,
    )


def full_decode(path: Path) -> None:
    subprocess.run(
        ["ffmpeg", "-v", "error", "-i", str(path), "-f", "null", "-"],
        check=True,
        capture_output=True,
        timeout=120,
    )


@pytest.mark.integration
def test_ffmpeg_probe_returns_finite_signals(tmp_path: Path) -> None:
    source = tmp_path / "probe.mp4"
    make_source(source, 6.0)
    signals = ffmpeg_probe(source, 2.5)
    assert 0.0 <= signals.y_avg <= 255.0
    assert signals.sat_avg >= 0.0
    assert signals.blur >= 0.0


@pytest.mark.integration
def test_discovery_extract_render_validates_end_to_end(tmp_path: Path) -> None:
    """Candidates from a real file extract at original offsets and render."""
    source = tmp_path / "long.mp4"
    make_source(source, 24.0)
    media_id = uuid4()
    metadata = MediaProbe().probe(source)

    found = discovery.discover_candidates(
        metadata.duration,
        str(media_id),
        lambda t: ffmpeg_probe(source, t),
        candidate_seconds=4.0,
        max_candidates=4,
        probes_per_stratum=3,
    )
    assert len(found) >= 2
    for candidate in found:
        assert 0 <= candidate.start_seconds < candidate.end_seconds
        assert candidate.end_seconds <= metadata.duration + 1e-6

    # Extract every candidate at its ORIGINAL offsets and verify durations.
    clips = []
    for index, candidate in enumerate(found):
        clip = extract_window(
            source,
            tmp_path / f"candidate_{index:02d}.mp4",
            start_seconds=candidate.start_seconds,
            end_seconds=candidate.end_seconds,
            video_stream_index=metadata.video.index,
            audio_stream_index=metadata.audio.index if metadata.audio else None,
        )
        actual = MediaProbe().probe(clip)
        expected = candidate.end_seconds - candidate.start_seconds
        assert abs(actual.duration - expected) < 0.25
        clips.append(clip)

    # Mocked Muse playback order over the real clips (no provider call).
    windows = [
        GroundedWindow(
            media_id=media_id,
            window_index=i,
            source_window_index=i,
            start_seconds=c.start_seconds,
            end_seconds=c.end_seconds,
            render_seconds=round(c.end_seconds - c.start_seconds, 6),
            clip=clip,
            sha256="00" * 32,
            summary="synthetic",
            observations=[],
        )
        for i, (c, clip) in enumerate(zip(found, clips, strict=True))
    ]
    order = sorted(range(len(windows)), key=lambda i: -found[i].score)
    selection = StorySelection.model_validate(
        {
            "title": "Local highlights",
            "rationale": "score-ordered mocked selection",
            "selected_windows": [
                {"window_index": i, "reason": f"local rank {rank + 1}"}
                for rank, i in enumerate(order)
            ],
        }
    )
    plan = build_edit_plan(selection, windows, [media_id], 30.0)
    assert len(plan.cuts) == len(windows)
    assert {c.media_id for c in plan.cuts} == {media_id}

    # Real render in AI playback order, then full-decode validation.
    ordered_clips = [windows[c.window_index].clip for c in plan.cuts]
    output = tmp_path / "highlights.mp4"
    result = render_vertical_mp4(ordered_clips, output)
    assert output.stat().st_size > 0
    assert result.metadata.video.width == 720
    assert result.metadata.video.height == 1280
    full_decode(output)
