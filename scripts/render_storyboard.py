import argparse
import hashlib
import math 
import json
from pathlib import Path
from intentcut.media.render import render_vertical_mp4


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()

    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)

    return digest.hexdigest()

def resolve_storyboard_clips(storyboard: Path) -> list[Path]:

    draft = json.loads(storyboard.read_text(encoding="utf-8"))
    cuts = draft["cuts"]

    if not isinstance(cuts, list) or not cuts:
        raise ValueError("Storyboard must contain cuts")

    clips = []
    seen = set()
    total_duration = 0.0
    source_media = None

    for cut in cuts:
        index = cut["window_index"]

        if type(index) is not int or index < 0 or index in seen:
            raise ValueError("Invalid or duplicate window index")

        seen.add(index)

        source = Path(cut["source_media"]).resolve(strict=True)

        if source_media is None:
            source_media = source
        elif source != source_media:
            raise ValueError("Mixed source media is not supported yet")

        evidence_path = storyboard.parent / f"window_{index:03d}.json"

        evidence = json.loads(
            evidence_path.read_text(encoding="utf-8")
        )

        if evidence["window_index"] != index:
            raise ValueError("Evidence window index mismatch")

        if evidence["source_media"] != str(source):
            raise ValueError("Evidence source mismatch")

        start = float(cut["start_seconds"])
        end = float(cut["end_seconds"])

        if not (
            math.isfinite(start)
            and math.isfinite(end)
            and 0 <= start < end
        ):
            raise ValueError("Invalid cut boundaries")

        for key, value in (
            ("window_start_seconds", start),
            ("window_end_seconds", end)
        ):
            if not math.isclose(
                float(evidence[key]),
                value, 
                rel_tol=0,
                abs_tol=1e-6,
            ):
                raise ValueError("Cut timestamps differ from evidence")

        clip = (
            Path(".local/windows")
            / source.stem
            / f"window_{index:03d}.mp4"
        )

        if not clip.is_file():
            raise FileNotFoundError(clip)

        if sha256_file(clip) != evidence["window_sha256"]:
            raise ValueError("Extracted clip fingerprint mismatch")

        total_duration += end - start
        clips.append(clip)

    target = float(draft["target_seconds"])

    if not math.isfinite(target) or target <= 0:
        raise ValueError("Invalid target duration")

    if total_duration > target + 1e-6:
        raise ValueError("Storyboard exceeds duration budget")

    return clips

def main() -> None:
    parser = argparse.ArgumentParser()

    parser.add_argument(
        "--storyboard",
        type=Path,
        default=Path(".local/ai/clip_b/storyboard_draft.json"),
    )

    parser.add_argument(
        "--output",
        type=Path,
        default=Path(".local/outputs/ai_first_cut.mp4"),
    )

    args = parser.parse_args()

    clips = resolve_storyboard_clips(args.storyboard)

    print("\n--- AI SELECTED TIMELINE ---")

    for index, clip in enumerate(clips, start=1):
        print(f"Cut {index}: {clip}")

    args.output.parent.mkdir(parents=True, exist_ok=True)

    if args.output.exists():
        raise FileExistsError(
            f"Output already exists: {args.output}"
        )

    print("\nRendering AI-directed first cut...")

    result = render_vertical_mp4(clips, args.output)

    print("\n--- RENDER RESULT ---")
    print(result)
    print(f"Output: {args.output}")


if __name__ == "__main__":
    main()
