import argparse
import json
import math
import os
import sys
from pathlib import Path

from openai import APIConnectionError, APIStatusError, APITimeoutError, OpenAI

from intentcut.ai.story_director import StorySelection, request_story


def load_evidence(directory: Path) -> dict[int, dict]:
    records = {}

    paths = sorted(directory.glob("window_*.json"))
    if not paths or len(paths) > 12:
        raise ValueError("Expected between 1 and 12 cached windows")

    source_media = None

    for path in paths:
        record = json.loads(path.read_text(encoding="utf-8"))

        index = record["window_index"]
        start = float(record["window_start_seconds"])
        end = float(record["window_end_seconds"])
        source = record["source_media"]

        if type(index) is not int or index < 0 or index in records:
            raise ValueError("Invalid or duplicate window index")

        if path.name != f"window_{index:03d}.json":
            raise ValueError("Cache filenamedoes not match window index")

        if not (math.isfinite(start) and math.isfinite(end) and 0 <= start < end):
            raise ValueError("Invalid window boundaries")

        if not isinstance(source, str) or not source.strip():
            raise ValueError("Missing source media")

        if source_media is None:
            source_media = source
        elif source != source_media:
            raise ValueError("Windows belong to different source files")

        if not isinstance(record["observations"], list):
            raise ValueError("Original source media is missing")

        records[index] = record

    if not Path(source_media).is_file():
        raise ValueError("Original source media is missing")

    return records


def validate_selection(
    selection: StorySelection,
    records: dict[int, dict],
    target_seconds: float,
) -> dict:
    if not math.isfinite(target_seconds) or target_seconds <= 0:
        raise ValueError("Invalid target duration")

    cuts = []
    total = 0.0

    for choice in selection.selected_windows:
        if choice.window_index not in records:
            raise ValueError("AI selected a nonexistent window")

        record = records[choice.window_index]
        start = record["window_start_seconds"]
        end = record["window_end_seconds"]

        total += end - start

        cuts.append(
            {
                "source_media": record["source_media"],
                "window_index": choice.window_index,
                "start_seconds": start,
                "end_seconds": end,
                "editorial_reason": choice.reason,
            }
        )

    if total > target_seconds + 1e-6:
        raise ValueError(
            f"Selected duration {total:.3f}s exceeds budget {target_seconds:.3f}s"
        )

    return {
        "title": selection.title,
        "rationale": selection.rationale,
        "target_seconds": target_seconds,
        "total_seconds": round(total, 6),
        "cuts": cuts,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--evidence",
        type=Path,
        default=Path(".local/ai/clip_b"),
    )
    parser.add_argument(
        "--intent",
        default=(
            "Create an engaging 10-second coding workspace video. "
            "Start with a room establishing shot and end with the "
            "computer monitor showing code. Avoid weak footage."
        ),
    )
    parser.add_argument("--target-seconds", type=float, default=10.0)
    parser.add_argument("--live", action="store_true")
    args = parser.parse_args()

    try:
        records = load_evidence(args.evidence)

        if not math.isfinite(args.target_seconds) or args.target_seconds <= 0:
            raise ValueError("Target duration must be positive and finite")

        evidence = [
            {
                "window_index": index,
                "start_seconds": record["window_start_seconds"],
                "end_seconds": record["window_end_seconds"],
                "summary": record["summary"],
                "observations": [
                    {
                        "description": item["description"],
                        "editorial_reason": item["editorial_reason"],
                    }
                    for item in record["observations"]
                ],
            }
            for index, record in sorted(records.items())
        ]

        print(f"Loaded {len(evidence)} grounded windows.")

        if not args.live:
            print("DRY RUN PASS — no Muse request made.")
            return 0

        api_key = os.getenv("MODEL_API_KEY")
        if not api_key:
            raise ValueError("MODEL_API_KEY is missing")

        with OpenAI(
            base_url="https://api.meta.ai/v1",
            api_key=api_key,
            timeout=90.0,
            max_retries=0,
        ) as client:
            selection, metrics = request_story(
                client, evidence, args.intent, args.target_seconds
            )

        draft = validate_selection(
            selection,
            records,
            args.target_seconds,
        )

        draft["metrics"] = metrics

        output = args.evidence / "storyboard_draft.json"
        pending = output.with_suffix(".json.tmp")

        pending.write_text(
            json.dumps(draft, indent=2),
            encoding="utf-8",
        )
        pending.replace(output)

        print("\n--- VALIDATED STORYBOARD ---")
        print(json.dumps(draft, indent=2))
        print(f"\nSaved: {output}")
        return 0

    except APIStatusError as exc:
        print(f"Meta API HTTP {exc.status_code}", file=sys.stderr)
    except (APIConnectionError, APITimeoutError) as exc:
        print(f"Network error: {type(exc).__name__}", file=sys.stderr)
    except (OSError, ValueError, KeyError, TypeError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)

    return 1


if __name__ == "__main__":
    sys.exit(main())
