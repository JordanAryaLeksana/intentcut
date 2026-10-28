"""Opt-in paid acceptance: real HTTP uploads, Muse worker, registered downloads."""

import argparse
import json
import sys
from contextlib import ExitStack
from pathlib import Path
from urllib.parse import urlsplit
from uuid import UUID

import httpx2 as httpx

from intentcut.backend.backend_settings import BackendSettings
from intentcut.backend.worker_cli import run_worker
from intentcut.media.probe_parser import MediaProbe
from intentcut.media.render import OutputValidator


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("videos", type=Path, nargs="+")
    parser.add_argument("--live", action="store_true", help="Authorize paid Meta calls")
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    parser.add_argument("--intent", default="Create a coherent story from these videos")
    parser.add_argument("--target-seconds", type=float, default=15)
    args = parser.parse_args()
    if not args.live:
        print(
            "No requests made. Add --live to authorize uploads and paid Meta inference."
        )
        return 0
    url = urlsplit(args.base_url)
    if url.scheme != "http" or url.hostname not in {"127.0.0.1", "localhost", "::1"}:
        parser.error("Only a directly connected local HTTP API is supported")
    try:
        settings = BackendSettings()
        if len(args.videos) > settings.ai_max_media:
            raise ValueError("Too many media files")
        with httpx.Client(
            base_url=args.base_url, timeout=180, trust_env=False
        ) as client:
            response = client.post("/projects", json={"name": "M2B9 live acceptance"})
            response.raise_for_status()
            project = response.json()["id"]
            with ExitStack() as stack:
                files = [
                    (
                        "files",
                        (
                            path.name,
                            stack.enter_context(path.open("rb")),
                            "application/octet-stream",
                        ),
                    )
                    for path in args.videos
                ]
                response = client.post(f"/projects/{project}/media", files=files)
            response.raise_for_status()
            media_ids = [item["id"] for item in response.json()["items"]]
            response = client.post(
                f"/projects/{project}/ai-jobs",
                json={
                    "kind": "first_cut",
                    "intent": args.intent,
                    "target_seconds": args.target_seconds,
                    "media_ids": media_ids,
                },
            )
            response.raise_for_status()
            if response.status_code != 202:
                raise RuntimeError("Job was not accepted")
            accepted = response.json()
            job_id = UUID(accepted["id"])
            print(
                f"Created job {job_id}; one attempt, up to 13 Muse calls."
            )
            if run_worker(settings, job_id=job_id) != 1:
                raise RuntimeError(
                    "Job could not be claimed; check matching API/worker DB"
                )
            status = client.get(accepted["status_url"])
            status.raise_for_status()
            if status.json()["status"] != "succeeded":
                print(
                    "Job did not succeed; safe code:", status.json().get("error_code")
                )
                return 1
            listing = client.get(accepted["status_url"] + "/artifacts")
            listing.raise_for_status()
            items = listing.json()["items"]
            if {item["kind"] for item in items} != {"video", "storyboard"}:
                raise RuntimeError("Missing registered artifacts")
            output = Path(".local/smoke") / str(job_id)
            output.mkdir(parents=True, mode=0o700)
            for item in items:
                response = client.get(item["download_url"])
                response.raise_for_status()
                suffix = "mp4" if item["kind"] == "video" else "json"
                with (output / f"{item['kind']}.{suffix}").open("xb") as stream:
                    stream.write(response.content)
            storyboard = json.loads((output / "storyboard.json").read_text())
            if any(cut["media_id"] not in media_ids for cut in storyboard["cuts"]):
                raise RuntimeError("Unexpected source identity")
            video = output / "video.mp4"
            metadata = MediaProbe().probe(video)
            OutputValidator().validate(metadata, storyboard["render_seconds"])
            OutputValidator().verify_playback(video, metadata.duration)
            print(
                f"PASS: job {job_id}; both artifacts downloaded and MP4 fully decoded."
            )
            print(f"Local downloads: {output}")
            return 0
    except Exception as exc:
        # Do not print provider/HTTP exception bodies or credentials.
        print(
            f"Smoke test failed ({type(exc).__name__}); inspect the safe job status.",
            file=sys.stderr,
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
