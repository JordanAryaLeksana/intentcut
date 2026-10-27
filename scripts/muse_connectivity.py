import argparse
import os
import subprocess
import sys
from pathlib import Path
from time import perf_counter

from openai import (
    APIConnectionError,
    APIStatusError,
    APITimeoutError,
    OpenAI,
)
from pydantic import ValidationError

from intentcut.ai.schemas import VideoUnderstandingResult, validate_scene_bounds

MODEL = "muse-spark-1.3"
MAX_TEST_BYTES = 25 * 1024 * 1024

PROMPT = (
    "You are IntentCut, an AI storytelling director. "
    "Analyze the attached raw video footage. "
    "Summarize what is visibly happening. "
    "Identify up to three visually interesting scene candidates. "
    "For each candidate, describe the visual content and explain "
    "its editorial storytelling value. "
    "Do not invent people, actions, dialogue, or events. "
    "For this first pass, always set start_seconds and "
    "end_seconds to null. "
    "We will determine timestamps through a separate process. "
    "Return a JSON object matching the provided schema."
)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("video", type=Path)
    args = parser.parse_args()

    video = args.video.expanduser().resolve()

    if not video.is_file() or video.suffix.lower() != ".mp4":
        print("ERROR: Provide an existing MP4 file.")
        return 2

    size = video.stat().st_size

    if not 0 < size <= MAX_TEST_BYTES:
        print("ERROR: Test file must be smaller than 25 MiB")
        return 2

    api_key = os.getenv("MODEL_API_KEY")

    if not api_key:
        print("ERROR: MODEL_API_KEY is missing")
        return 2

    client = OpenAI(
        base_url="https://api.meta.ai/v1",
        api_key=api_key,
        timeout=180.0,
        max_retries=0,
    )

    file_id = None

    try:
        print("Uploading video to Meta Files API...")

        start = perf_counter()

        with video.open("rb") as source:
            uploaded = client.files.create(
                file=source,
                purpose="user_data",
                expires_after={
                    "anchor": "created_at",
                    "seconds": 3600,
                },
            )

        file_id = uploaded.id
        uploaded_latency = perf_counter() - start

        print(f"Upload successful: {file_id}")
        print(f"Upload latency: {uploaded_latency:.2f}s")

        print("\nRunning Muse Spark video understanding...")

        start = perf_counter()

        response = client.responses.create(
            model=MODEL,
            store=False,
            reasoning={"effort": "low"},
            max_output_tokens=2000,
            input=[
                {
                    "type": "message",
                    "role": "user",
                    "content": [
                        {
                            "type": "input_text",
                            "text": PROMPT,
                        },
                        {
                            "type": "input_file",
                            "file_id": file_id,
                        },
                    ],
                }
            ],
            text={
                "format": {
                    "type": "json_schema",
                    "name": "video_understanding",
                    "strict": True,
                    "schema": VideoUnderstandingResult.model_json_schema(),
                }
            },
        )

        inference_latency = perf_counter() - start

        print("\n--- INFERENCE METRICS ---")
        print(f"Model: {response.model}")
        print(f"Status: {response.status}")
        print(f"Inference latency: {inference_latency:.2f}s")

        if response.usage:
            usage = response.usage

            print(f"Input tokens: {usage.input_tokens}")
            print(f"Output tokens: {usage.output_tokens}")
            print(f"Total tokens: {usage.total_tokens}")

        output = response.output_text or ""

        print("\n--- MUSE VIDEO ANALYSIS ---")
        print(output)

        if response.status != "completed" or not output.strip():
            print("ERROR: Model did nor return a completed response.")
            return 1

        result = VideoUnderstandingResult.model_validate_json(output)

        # real duration from FFprobe
        probe = subprocess.run(
            [
                "ffprobe",
                "-v",
                "error",
                "-show_entries",
                "format=duration",
                "-of",
                "default=noprint_wrappers=1:nokey=1",
                str(video),
            ],
            capture_output=True,
            text=True,
            check=True,
            timeout=15,
        )

        duration = float(probe.stdout.strip())
        validate_scene_bounds(result, duration)
        print("\n--- VALIDATED SCENE CANDIDATES ---")
        print(result.model_dump_json(indent=2))

        print(f"\nVideo duration: {duration:.3f}s")
        print(f"Validated scenes: {len(result.scene_candidates)}")
        return 0

    except APIStatusError as exc:
        print(f"Meta API error: HTTP {exc.status_code}")
        print(f"Meta API error: Message {exc.message}")
        return 1
    except (APIConnectionError, APITimeoutError) as exc:
        print(f"Connection error: {type(exc).__name__}")
        return 1
    except OSError as exc:
        print(f"Local file error: {exc}")
        return 1
    except (ValidationError, ValueError) as exc:
        print(f"Structured output validation failed: {exc}")
        return 1

    except (
        subprocess.CalledProcessError,
        subprocess.TimeoutExpired,
    ) as exc:
        print(f"FFprobe failed: {type(exc).__name__}")
        return 1
    
    finally:
        try:
            client.files.delete(file_id)
            print("\nRemote test file deleted.")
        except Exception:
            print(
                f"WARNING: Remote cleanup failed for {file_id}.",
                file=sys.stderr,
            )
        client.close()


if __name__ == "__main__":
    sys.exit(main())
