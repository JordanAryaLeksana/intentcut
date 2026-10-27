
import argparse
import hashlib
import json
import os
import subprocess
import sys
from dataclasses import asdict
from pathlib import Path
from time import perf_counter

from openai import APIConnectionError, APIStatusError, APITimeoutError, OpenAI

from intentcut.ai.schemas import VideoUnderstandingResult
from intentcut.ai.temporal_windows import plan_temporal_window
from intentcut.ai.window_analysis import to_window_evidence

MODEL = "muse-spark-1.3"
MAX_CLIP_BYTES = 25 * 1024 * 1024

PROMPT = (
    "You are IntentCut's video editor. Analyze only this short video. "
    "Describe what is visibly present and identify up to three useful "
    "visual moments and their editorial value. Do not invent events or "
    "dialogue. Always set start_seconds and end_seconds to null because "
    "source timestamps are assigned outside the model."
)


def probe_duration(path: Path) -> float:
    result = subprocess.run(
        [
            "ffprobe",
            "-v", "error",
            "-show_entries", "format=duration",
            "-of", "default=noprint_wrappers=1:nokey=1",
            str(path),
        ],
        capture_output=True,
        text=True,
        check=True,
        timeout=15,
    )
    return float(result.stdout.strip())


def file_digest(path: Path) -> str:
    digest = hashlib.sha256()

    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)

    return digest.hexdigest()


def analyze_one(
    client: OpenAI,
    clip: Path,
) -> tuple[VideoUnderstandingResult, dict]:
    remote_id = None

    try:
        started = perf_counter()

        with clip.open("rb") as source:
            uploaded = client.files.create(
                purpose="user_data",
                expires_after={
                    "anchor": "created_at",
                    "seconds": 3600,
                },
                file=source,
            )

        remote_id = uploaded.id
        upload_seconds = perf_counter() - started

        started = perf_counter()

        response = client.responses.create(
            model=MODEL,
            store=False,
            reasoning={"effort": "low"},
            max_output_tokens=1500,
            text={
                "format": {
                    "type": "json_schema",
                    "name": "video_understanding",
                    "strict": True,
                    "schema": VideoUnderstandingResult.model_json_schema(),
                }
            },
            input=[
                {
                    "type": "message",
                    "role": "user",
                    "content": [
                        {"type": "input_text", "text": PROMPT},
                        {"type": "input_file", "file_id": remote_id},
                    ],
                }
            ],
        )

        inference_seconds = perf_counter() - started

        if response.status != "completed" or not response.output_text:
            raise RuntimeError("Muse returned an incomplete or empty response")

        parsed = VideoUnderstandingResult.model_validate_json(
            response.output_text
        )

        usage = response.usage

        return parsed, {
            "upload_seconds": round(upload_seconds, 3),
            "inference_seconds": round(inference_seconds, 3),
            "input_tokens": usage.input_tokens if usage else None,
            "output_tokens": usage.output_tokens if usage else None,
            "total_tokens": usage.total_tokens if usage else None,
        }

    finally:
        if remote_id is not None:
            try:
                client.files.delete(remote_id)
            except Exception:
                print(
                    "WARNING: Remote cleanup failed; "
                    "file expires in one hour.",
                    file=sys.stderr,
                )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("source", type=Path)
    parser.add_argument(
        "--live",
        action="store_true",
        help="Allow paid API calls",
    )
    parser.add_argument(
        "--max-new",
        type=int,
        choices=(1, 2, 3),
        default=1,
    )
    args = parser.parse_args()

    client = None

    try:
        source = args.source.expanduser().resolve()

        if not source.is_file():
            raise FileNotFoundError(source)

        windows = plan_temporal_window(probe_duration(source))
        clips = Path(".local/windows") / source.stem
        cache_dir = Path(".local/ai") / source.stem

        planned = []

        for window in windows:
            clip = clips / f"window_{window.index:03d}.mp4"

            if (
                not clip.is_file()
                or not 0 < clip.stat().st_size <= MAX_CLIP_BYTES
            ):
                raise ValueError(
                    f"Missing or oversized extracted clip: {clip}"
                )

            expected = {
                "model": MODEL,
                "source_media": str(source),
                "window_index": window.index,
                "window_start_seconds": window.start_seconds,
                "window_end_seconds": window.end_seconds,
                "window_sha256": file_digest(clip),
            }

            cache = cache_dir / f"window_{window.index:03d}.json"
            cached = cache.is_file()

            if cached:
                old = json.loads(cache.read_text(encoding="utf-8"))

                if any(
                    old.get(key) != value
                    for key, value in expected.items()
                ):
                    raise ValueError(f"Stale cache found: {cache}")

            planned.append((window, clip, cache, cached, expected))

            status = "CACHED" if cached else "NEW"

            print(
                f"Window {window.index}: "
                f"{window.start_seconds:.3f}-"
                f"{window.end_seconds:.3f}s — {status}"
            )

        if not args.live:
            print("Dry run only. Use --live to allow Meta API calls.")
            return 0

        if not os.getenv("MODEL_API_KEY"):
            raise ValueError("MODEL_API_KEY is missing")

        client = OpenAI(
            base_url="https://api.meta.ai/v1",
            api_key=os.environ["MODEL_API_KEY"],
            timeout=180.0,
            max_retries=0,
        )

        cache_dir.mkdir(parents=True, exist_ok=True)
        new_calls = 0

        for window, clip, cache, cached, expected in planned:
            if cached:
                continue

            if new_calls == args.max_new:
                break

            print(f"Analyzing window {window.index} through Muse...")

            result, metrics = analyze_one(client, clip)

            observations = to_window_evidence(
                str(source),
                window,
                result,
            )

            record = {
                **expected,
                "timing_precision": "coarse_window",
                "summary": result.summary,
                "observations": [
                    asdict(item) for item in observations
                ],
                "metrics": metrics,
            }

            pending = cache.with_suffix(".json.tmp")
            pending.write_text(
                json.dumps(record, indent=2),
                encoding="utf-8",
            )
            pending.replace(cache)

            new_calls += 1

            print(f"Saved {len(observations)} observations: {cache}")
            print(f"Tokens: {metrics['total_tokens']}")

        print(f"Completed {new_calls} new inference request(s).")
        return 0

    except APIStatusError as exc:
        print(
            f"Meta returned HTTP {exc.status_code}",
            file=sys.stderr,
        )
    except (APIConnectionError, APITimeoutError) as exc:
        print(
            f"Meta connection failed: {type(exc).__name__}",
            file=sys.stderr,
        )
    except (
        OSError,
        ValueError,
        RuntimeError,
        subprocess.SubprocessError,
    ) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
    finally:
        if client is not None:
            client.close()

    return 1


if __name__ == "__main__":
    sys.exit(main())
