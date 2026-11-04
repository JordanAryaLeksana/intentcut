
"""Replay Story Selection using validated, job-local cached footage evidence.

Default: offline validation only.
--live: permits at most one Muse Story Selection request per job.
"""
import argparse
import json
import math
import os
from pathlib import Path
from uuid import UUID

from openai import OpenAI
from sqlalchemy import create_engine, text

from intentcut.ai.story_director import (
    StoryChoice,
    StorySelection,
    build_edit_plan,
    request_story,
)
from intentcut.ai.temporal_windows import TemporalWindow
from intentcut.ai.video_understanding import (
    PreparedWindow,
    WindowUnderstanding,
    file_digest,
)
from intentcut.backend.shared.settings import BackendSettings
from intentcut.media.probe_parser import MediaProbe
from intentcut.media.settings import FPS

JOB_ID = "77c9a915-53cc-4eb6-8a64-f5e6cc8846df"


class NoInference:
    def analyze(self, clip):
        raise RuntimeError("Video inference is BLOCKED")

    def select(self, *args):
        raise RuntimeError("Unexpected Story Selection request")


class ResponseRecorder:
    """Persist the API response before request_story parses it."""

    def __init__(self, client, destination):
        self.client = client
        self.destination = destination
        self.responses = self

    def create(self, **kwargs):
        response = self.client.responses.create(**kwargs)

        data = {
            "status": response.status,
            "incomplete_reason": getattr(
                getattr(response, "incomplete_details", None),
                "reason",
                None,
            ),
            "error_code": getattr(
                getattr(response, "error", None),
                "code",
                None,
            ),
            "input_tokens": getattr(
                response.usage, "input_tokens", None
            ),
            "output_tokens": getattr(
                response.usage, "output_tokens", None
            ),
            "output_text": response.output_text or "",
        }

        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
        flags |= getattr(os, "O_NOFOLLOW", 0)
        fd = os.open(self.destination, flags, 0o600)

        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump(data, stream)
            stream.flush()
            os.fsync(stream.fileno())

        return response


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--live", action="store_true")
    args = parser.parse_args()

    settings = BackendSettings()
    root = Path(".local/media/.jobs") / JOB_ID
    cache = root / "cache"
    saved = root / "story_selection_response.json"
    plan_file = root / "recovered_edit_plan.json"

    # Retrieve original request, including the selected media order.
    engine = create_engine(settings.database_url.get_secret_value())
    try:
        with engine.connect() as conn:
            payload = conn.execute(
                text(
                    "SELECT request_payload FROM ai_jobs "
                    "WHERE id = :job_id"
                ),
                {"job_id": JOB_ID},
            ).scalar_one()
    finally:
        engine.dispose()

    if isinstance(payload, str):
        payload = json.loads(payload)

    media_ids = [str(value) for value in payload["media_ids"]]
    target = float(payload["target_seconds"])
    source_hashes = payload["source_sha256"]

    intent = next(
        (
            payload[key]
            for key in (
                "intent",
                "story_intent",
                "user_intent",
                "story_prompt",
                "story_idea",
                "prompt",
                "creative_brief",
                "description",
            )
            if isinstance(payload.get(key), str)
            and payload[key].strip()
        ),
        None,
    )

    if not intent:
        raise SystemExit(
            "STOP: Original story intent field not identified. "
            f"Payload keys: {sorted(payload)}"
        )

    # Cache mapping: hash-based filenames must never define timeline order.
    identities = {}
    for path in cache.glob("*.json"):
        data = json.loads(path.read_text())
        ident = data["identity"]
        key = (ident["media_id"], ident["source_window_index"])
        assert key not in identities, "Duplicate cached window"
        identities[key] = ident

    understanding = WindowUnderstanding(NoInference())
    probe = MediaProbe()
    windows = []

    for media_id in media_ids:
        indices = sorted(
            index for mid, index in identities if mid == media_id
        )
        assert indices == list(range(len(indices)))

        for index in indices:
            ident = identities[(media_id, index)]
            clips = list(
                root.glob(
                    f"attempt_*/{media_id}/window_{index:03d}.mp4"
                )
            )
            assert len(clips) == 1, "Missing/ambiguous clip"

            clip = clips[0]
            source = clip.parent / "source"

            assert source.is_file()
            assert file_digest(source) == ident["source_sha256"]
            assert source_hashes[media_id] == ident["source_sha256"]
            assert file_digest(clip) == ident["window_sha256"]

            interval = TemporalWindow(
                index=index,
                start_seconds=ident["start_seconds"],
                end_seconds=ident["end_seconds"],
            )

            actual = probe.probe(clip)

            assert abs(
                actual.duration - interval.duration_seconds
            ) <= 0.1

            prepared = PreparedWindow(
                media_id=UUID(media_id),
                index=len(windows),
                window=interval,
                source_sha256=ident["source_sha256"],
                clip=clip,
                sha256=ident["window_sha256"],
                render_seconds=math.ceil(
                    actual.duration * FPS - 1e-7
                ) / FPS,
            )

            assert understanding.cache_path(
                prepared, cache
            ).is_file()

            window = understanding.analyze(
                prepared,
                cache,
                lambda: (_ for _ in ()).throw(
                    RuntimeError("Live video inference attempted")
                ),
            )
            windows.append(window)

    assert len(windows) == len(identities) == 26
    evidence = [window.public_evidence() for window in windows]
    allowed_ids = [UUID(value) for value in media_ids]

    print("PASS: 26 cached windows verified")
    print("PASS: Original request recovered")
    print("Target:", target, "seconds")

    # Test the actual EditPlan validator using a synthetic,
    # duration-bounded selection. This does NOT replace AI selection.
    choices = []
    source_total = 0.0
    render_total = 0.0

    for window in windows:
        duration = window.end_seconds - window.start_seconds
        if max(
            source_total + duration,
            render_total + window.render_seconds,
        ) <= target + 1e-6 and len(choices) < 12:
            choices.append(
                StoryChoice(
                    window_index=window.window_index,
                    reason="Offline validation",
                )
            )
            source_total += duration
            render_total += window.render_seconds

    assert choices, "No cuts fit the target"

    offline_selection = StorySelection(
        title="Offline validation",
        rationale="Check the 60-second EditPlan contract",
        selected_windows=choices,
    )

    offline_plan = build_edit_plan(
        offline_selection,
        windows,
        allowed_ids,
        target,
    )

    print(
        "PASS: Offline EditPlan validation:",
        len(offline_plan.cuts),
        "cuts,",
        offline_plan.render_seconds,
        "render seconds",
    )

    if not saved.exists() and not args.live:
        print("SAFE: No Muse API requests made")
        print("Run with --live only after reviewing preflight")
        return

    if not saved.exists():
        print("LIVE: Sending ONE Story Selection request")
        with OpenAI(
            base_url="https://api.meta.ai/v1",
            api_key=settings.model_api_key.get_secret_value(),
            timeout=180.0,
            max_retries=0,
        ) as client:
            recorder = ResponseRecorder(client, saved)
            try:
                request_story(
                    recorder,
                    evidence,
                    intent,
                    target,
                    max_output_tokens=settings.ai_story_max_output_tokens,
                )
            except Exception as exc:
                print(
                    "Story Selection failed:",
                    type(exc).__name__,
                    str(exc)[:300],
                )
                if saved.exists():
                    print("API response saved:", saved)
                raise SystemExit(1) from None

    # A saved response is always reused: never automatically call Muse again.
    response = json.loads(saved.read_text())

    print("Response status:", response["status"])
    print("Incomplete reason:", response["incomplete_reason"])
    print("Output tokens:", response["output_tokens"])

    if response["status"] != "completed":
        raise SystemExit("STOP: Story Selection response not completed")

    selection = StorySelection.model_validate_json(
        response["output_text"]
    )

    plan = build_edit_plan(
        selection,
        windows,
        allowed_ids,
        target,
    )

    plan_file.write_text(
        plan.model_dump_json(indent=2),
        encoding="utf-8",
    )

    print("PASS: Story Selection and EditPlan")
    print("Selected cuts:", len(plan.cuts))
    print("Rendered duration:", plan.render_seconds)
    print("EditPlan saved:", plan_file)


if __name__ == "__main__":
    main()
