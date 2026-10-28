"""Proven M2A Muse transport, shared by scripts and uploaded-media jobs."""

import sys
from pathlib import Path
from time import perf_counter

from openai import OpenAI

from intentcut.ai.schemas import VideoUnderstandingResult

MODEL = "muse-spark-1.3"
MAX_CLIP_BYTES = 25 * 1024 * 1024

PROMPT = (
    "You are IntentCut's video editor. Analyze only this short video. "
    "Describe what is visibly present and identify up to three useful "
    "visual moments and their editorial value. Do not invent events or "
    "dialogue. Always set start_seconds and end_seconds to null because "
    "source timestamps are assigned outside the model."
)


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

        parsed = VideoUnderstandingResult.model_validate_json(response.output_text)

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
                    "WARNING: Remote cleanup failed; file expires in one hour.",
                    file=sys.stderr,
                )


class MuseClient:
    """Thin reusable facade; caller owns and closes the configured OpenAI client."""

    def __init__(self, client: OpenAI) -> None:
        self.client = client

    def analyze(self, clip: Path) -> VideoUnderstandingResult:
        result, _ = analyze_one(self.client, clip)
        return result

    def select(self, evidence: list[dict], intent: str, target_seconds: float):
        from intentcut.ai.story_director import request_story

        selection, _ = request_story(self.client, evidence, intent, target_seconds)
        return selection
