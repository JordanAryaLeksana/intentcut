"""Bounded coarse-to-fine visual retrieval with immutable source-time mapping.

Uniform coarse frames include the tail of the source. Fine frames cover the
neighborhood of the strongest coarse matches. Unsampled short events can be
missed; neither this module nor its score claims exhaustive video understanding.
"""

import math
import subprocess
from dataclasses import dataclass
from pathlib import Path

from intentcut.ai.highlight_retrieval import BATCH_SIZE, validate_ranking
from intentcut.backend.contracts import AIProcessingError
from intentcut.backend.highlights.discovery import Candidate, center_window

COARSE_SAMPLES = 48
FINE_SAMPLES = 24
MAX_RANK_CALLS = math.ceil(COARSE_SAMPLES / BATCH_SIZE) + math.ceil(
    FINE_SAMPLES / BATCH_SIZE
)


@dataclass(frozen=True)
class RankedSample:
    index: int
    seconds: float
    relevance: float


def coarse_times(duration: float, count: int = COARSE_SAMPLES) -> list[float]:
    if not math.isfinite(duration) or duration <= 0 or not 2 <= count <= COARSE_SAMPLES:
        raise ValueError("Invalid sampling bounds")
    count = min(count, max(2, math.ceil(duration / 2) + 1))
    # Keep the final sample decodable even at very short durations.
    end = max(0, duration - min(0.1, duration / 2))
    return sorted({round(i * end / (count - 1), 6) for i in range(count)})


def fine_times(
    duration: float, coarse: list[RankedSample], count: int = FINE_SAMPLES
) -> list[float]:
    if not coarse or not 2 <= count <= FINE_SAMPLES:
        raise ValueError("Invalid refinement bounds")
    # Two separate neighborhoods, never a fresh prefix-only scan.
    radius = duration / max(1, len(coarse) - 1)
    seeds = []
    for sample in sorted(coarse, key=lambda s: (-s.relevance, s.seconds)):
        if all(abs(sample.seconds - other.seconds) >= radius for other in seeds):
            seeds.append(sample)
        if len(seeds) == 2:
            break
    per_seed = count // len(seeds)
    existing = {s.seconds for s in coarse}
    return sorted(
        {
            round(
                min(
                    max(seed.seconds + radius * (2 * (i + 1) / (per_seed + 1) - 1), 0),
                    max(0, duration - 0.1),
                ),
                6,
            )
            for seed in seeds
            for i in range(per_seed)
        }
        - existing
    )


def select_candidates(
    samples: list[RankedSample],
    duration: float,
    media_id: str,
    seconds: float,
    limit: int,
) -> list[Candidate]:
    if not 1 <= limit <= 12 or not 0 < seconds <= 30:
        raise ValueError("Invalid candidate bounds")
    found = []
    for sample in sorted(samples, key=lambda s: (-s.relevance, s.seconds)):
        if sample.relevance < 0.25:
            continue
        start, end = center_window(sample.seconds, duration, seconds)
        if any(start < c.end_seconds and end > c.start_seconds for c in found):
            continue
        found.append(
            Candidate(
                "",
                media_id,
                start,
                end,
                sample.relevance,
                {"relevance": sample.relevance},
                sample.seconds,
            )
        )
        if len(found) == limit:
            break
    found.sort(key=lambda c: c.start_seconds)
    return [
        Candidate(
            f"hl-{i + 1:02d}",
            c.media_id,
            c.start_seconds,
            c.end_seconds,
            c.score,
            c.components,
            c.probe_seconds,
        )
        for i, c in enumerate(found)
    ]


def sample_frame(source: Path, target: Path, seconds: float, stream_index: int):
    try:
        subprocess.run(
        [
            "ffmpeg",
            "-v",
            "error",
            "-nostdin",
            "-n",
            "-ss",
            f"{seconds:.6f}",
            "-i",
            str(source),
            "-map",
            f"0:{stream_index}",
            "-frames:v",
            "1",
            "-vf",
            "scale=320:-2",
            "-q:v",
            "5",
            str(target),
        ],
        check=True,
        capture_output=True,
        timeout=30,
    )
    except (subprocess.SubprocessError, OSError) as exc:
        raise AIProcessingError("source_unavailable") from exc
    if not target.is_file() or not 0 < target.stat().st_size <= 256 * 1024:
        raise AIProcessingError("source_unavailable")


def retrieve(
    source,
    directory,
    duration,
    media_id,
    intent,
    seconds,
    limit,
    muse,
    before_call,
    before_frame,
    progress,
    stream_index=0,
):
    directory.mkdir(mode=0o700, exist_ok=True)
    ranked: list[RankedSample] = []
    sent_bytes = 0

    def rank(times):
        nonlocal sent_bytes
        samples = []
        for offset, moment in enumerate(times):
            before_frame()
            index = len(ranked) + offset
            frame = directory / f"sample-{index}.jpg"
            sample_frame(source, frame, moment, stream_index)
            sent_bytes += frame.stat().st_size
            samples.append((index, moment, frame))
        for offset in range(0, len(samples), BATCH_SIZE):
            batch = samples[offset : offset + BATCH_SIZE]
            before_call(sent_bytes)
            result = muse.rank_highlights(batch, intent)
            scores = {
                s.sample_id: s.relevance
                for s in validate_ranking(result, [item[0] for item in batch])
            }
            ranked.extend(RankedSample(i, t, scores[i]) for i, t, _ in batch)

    progress("discovering_highlights")
    coarse = coarse_times(duration)
    rank(coarse)
    progress("refining_highlights")
    rank(fine_times(duration, ranked))
    found = select_candidates(ranked, duration, media_id, seconds, limit)
    if not found:
        raise AIProcessingError("no_relevant_highlights")
    return (
        found,
        sent_bytes,
        {
            "coarse_samples": len(coarse),
            "fine_samples": len(ranked) - len(coarse),
            "source_duration_seconds": duration,
            "max_coarse_gap_seconds": max(
                b - a for a, b in zip(coarse, coarse[1:], strict=False)
            ),
        },
    )
