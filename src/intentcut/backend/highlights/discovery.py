"""Stratified local candidate discovery for long-form sources.

Scans the full source timeline with a bounded number of deterministic FFmpeg
frame probes, scores inexpensive visual-heuristic signals (exposure, color,
sharpness), and returns a bounded list of candidate moments. The heuristics
measure pixels, not meaning: they MUST NOT be presented as semantic
understanding. Semantic selection happens later in Muse/Story Director.

Candidate boundaries ARE original source offsets (identity mapping). The
downstream pipeline extracts windows at these exact offsets and Muse selects
window indices only, so no timestamp is ever invented or rebased.
"""

import re
import subprocess
from collections.abc import Callable
from dataclasses import dataclass
from math import isfinite
from pathlib import Path

from intentcut.media.models import MediaProcessError, MissingBinaryError

PROBE_TIMEOUT = 30.0
_MAX_PROBES_HARD = 256

_SIGNAL_RE = re.compile(r"lavfi\.signalstats\.(YAVG|SATAVG)=([0-9.]+)")
_BLUR_RE = re.compile(r"lavfi\.blur=([0-9.]+)")


@dataclass(frozen=True, slots=True)
class FrameSignals:
    """One frame's inexpensive visual signals. Pixels only, no semantics."""

    y_avg: float
    sat_avg: float
    blur: float


@dataclass(frozen=True, slots=True)
class Candidate:
    id: str
    media_id: str
    start_seconds: float
    end_seconds: float
    score: float
    components: dict[str, float]
    probe_seconds: float


def _check_bounds(
    duration_seconds: float,
    candidate_seconds: float,
    max_candidates: int,
    probes_per_stratum: int,
    min_gap_seconds: float,
) -> None:
    if not isfinite(duration_seconds) or duration_seconds <= 0:
        raise ValueError("Source duration must be positive and finite")
    if not isfinite(candidate_seconds) or not 0 < candidate_seconds <= 120:
        raise ValueError("Candidate duration must be within (0, 120]")
    if (
        isinstance(max_candidates, bool)
        or not isinstance(max_candidates, int)
        or not 1 <= max_candidates <= 12
    ):
        raise ValueError("max_candidates must be an integer within [1, 12]")
    if (
        isinstance(probes_per_stratum, bool)
        or not isinstance(probes_per_stratum, int)
        or not 1 <= probes_per_stratum <= 16
    ):
        raise ValueError("probes_per_stratum must be an integer within [1, 16]")
    if not isfinite(min_gap_seconds) or not 0 <= min_gap_seconds <= 60:
        raise ValueError("min_gap_seconds must be within [0, 60]")
    if max_candidates * probes_per_stratum > _MAX_PROBES_HARD:
        raise ValueError("Probe budget exceeded")


def score_signals(signals: FrameSignals) -> tuple[float, dict[str, float]]:
    """Score one probe. Deterministic; higher means stronger heuristic cues."""
    exposure = max(0.0, 1.0 - abs(signals.y_avg - 128.0) / 128.0)
    color = max(0.0, min(1.0, signals.sat_avg / 128.0))
    sharpness = 1.0 / (1.0 + max(0.0, signals.blur) / 10.0)
    components = {
        "exposure": round(exposure, 6),
        "color": round(color, 6),
        "sharpness": round(sharpness, 6),
    }
    score = round(
        0.3 * components["exposure"]
        + 0.4 * components["color"]
        + 0.3 * components["sharpness"],
        6,
    )
    return score, components


def plan_probes(
    duration_seconds: float, strata: int, probes_per_stratum: int
) -> list[float]:
    """Deterministic probe timestamps giving every stratum equal coverage."""
    probes: list[float] = []
    width = duration_seconds / strata
    for s in range(strata):
        for p in range(probes_per_stratum):
            t = (s + (p + 1) / (probes_per_stratum + 1)) * width
            probes.append(round(min(max(t, 0.0), duration_seconds), 6))
    return probes


def center_window(
    center: float, duration_seconds: float, candidate_seconds: float
) -> tuple[float, float]:
    """Clamp a candidate window to [0, duration]; short sources yield one span."""
    if duration_seconds <= candidate_seconds:
        return 0.0, duration_seconds
    start = min(
        max(center - candidate_seconds / 2.0, 0.0),
        duration_seconds - candidate_seconds,
    )
    return round(start, 6), round(start + candidate_seconds, 6)


def _overlaps(a: Candidate, b_start: float, b_end: float, gap: float) -> bool:
    return not (b_end + gap <= a.start_seconds or b_start >= a.end_seconds + gap)


def discover_candidates(
    duration_seconds: float,
    media_id: str,
    sampler: Callable[[float], FrameSignals],
    *,
    candidate_seconds: float = 8.0,
    max_candidates: int = 8,
    probes_per_stratum: int = 5,
    min_gap_seconds: float = 1.0,
) -> list[Candidate]:
    """Pick up to max_candidates moments spanning the full source timeline.

    One winner per stratum guarantees coverage; score-ordered non-maximum
    suppression removes near-duplicates across stratum borders. Output is
    sorted by start time with stable rank-based IDs.
    """
    _check_bounds(
        duration_seconds,
        candidate_seconds,
        max_candidates,
        probes_per_stratum,
        min_gap_seconds,
    )
    if not media_id.strip():
        raise ValueError("media_id is required")
    strata = max_candidates
    probes = plan_probes(duration_seconds, strata, probes_per_stratum)
    winners: list[tuple[float, dict[str, float], float]] = []
    for s in range(strata):
        cells = probes[s * probes_per_stratum : (s + 1) * probes_per_stratum]
        scored = []
        for t in cells:
            score, components = score_signals(sampler(t))
            scored.append((score, components, t))
        scored.sort(key=lambda item: (-item[0], item[2]))
        winners.append(scored[0])
    winners.sort(key=lambda item: (-item[0], item[2]))
    picked: list[Candidate] = []
    for score, components, t in winners:
        start, end = center_window(t, duration_seconds, candidate_seconds)
        if any(_overlaps(kept, start, end, min_gap_seconds) for kept in picked):
            continue
        picked.append(
            Candidate(
                id="",
                media_id=media_id,
                start_seconds=start,
                end_seconds=end,
                score=score,
                components=components,
                probe_seconds=t,
            )
        )
        if len(picked) >= max_candidates:
            break
    picked.sort(key=lambda c: (c.start_seconds, c.end_seconds))
    return [
        Candidate(
            id=f"hl-{index + 1:02d}",
            media_id=c.media_id,
            start_seconds=c.start_seconds,
            end_seconds=c.end_seconds,
            score=c.score,
            components=c.components,
            probe_seconds=c.probe_seconds,
        )
        for index, c in enumerate(picked)
    ]


def ffmpeg_probe(source: Path, at_seconds: float) -> FrameSignals:
    """Sample one frame's signals with a bounded, seek-first FFmpeg call."""
    if not source.is_file():
        raise FileNotFoundError(f"Source video not found: {source}")
    if not isfinite(at_seconds) or at_seconds < 0:
        raise ValueError("Probe timestamp must be non-negative and finite")
    try:
        result = subprocess.run(
            [
                "ffmpeg",
                "-hide_banner",
                "-nostdin",
                "-ss",
                f"{at_seconds:.6f}",
                "-i",
                str(source),
                "-an",
                "-frames:v",
                "1",
                "-vf",
                "scale=160:-1,signalstats,blurdetect,metadata=mode=print",
                "-f",
                "null",
                "-",
            ],
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=True,
            timeout=PROBE_TIMEOUT,
        )
    except FileNotFoundError as exc:
        raise MissingBinaryError(
            "Required executable 'ffmpeg' was not found; install it on PATH."
        ) from exc
    except subprocess.TimeoutExpired as exc:
        raise MediaProcessError(
            f"ffmpeg probe timed out after {PROBE_TIMEOUT:.0f} seconds."
        ) from exc
    except subprocess.CalledProcessError as exc:
        detail = (exc.stderr or "No diagnostic output.")[-2000:].strip()
        raise MediaProcessError(f"ffmpeg probe failed: {detail}") from exc
    signals = dict(_SIGNAL_RE.findall(result.stderr))
    blurs = _BLUR_RE.findall(result.stderr)
    try:
        # A seek may emit more than one analyzed frame; the last one is the
        # frame nearest the requested timestamp.
        return FrameSignals(
            y_avg=float(signals["YAVG"]),
            sat_avg=float(signals["SATAVG"]),
            blur=float(blurs[-1]),
        )
    except (KeyError, IndexError, ValueError) as exc:
        raise MediaProcessError("ffmpeg probe returned no frame signals.") from exc
