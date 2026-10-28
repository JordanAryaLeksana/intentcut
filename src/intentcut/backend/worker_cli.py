"""Bounded local worker command; provider credentials are never printed."""

import argparse
import sys
from uuid import UUID

from openai import OpenAI

from intentcut.ai.muse import MuseClient
from intentcut.backend.ai_artifacts import AIArtifactPublisher
from intentcut.backend.ai_media_inputs import processing_available
from intentcut.backend.ai_processing_adapter import RealAIProcessingAdapter
from intentcut.backend.ai_worker import AIJobWorker
from intentcut.backend.backend_settings import BackendSettings
from intentcut.backend.database import Database
from intentcut.backend.local_media_storage import LocalMediaStorage


def run_worker(
    settings: BackendSettings,
    *,
    max_jobs: int = 1,
    max_attempts: int = 1,
    job_id: UUID | None = None,
) -> int:
    if not processing_available(settings):
        raise ValueError("Uploaded-media processing is not configured")
    if not 1 <= max_jobs <= 100 or not 1 <= max_attempts <= 3:
        raise ValueError("Invalid worker budget")
    database = Database.connect(settings.database_url.get_secret_value())
    try:
        storage = LocalMediaStorage(
            settings.media_root, settings.max_file_bytes, settings.copy_chunk_bytes
        )
        storage.initialize()
        with OpenAI(
            base_url="https://api.meta.ai/v1",
            api_key=settings.model_api_key.get_secret_value(),
            timeout=180.0,
            max_retries=0,
        ) as client:
            processor = RealAIProcessingAdapter(
                database=database,
                storage=storage,
                settings=settings,
                muse=MuseClient(client),
            )
            worker = AIJobWorker(
                database, processor, artifact_publisher=AIArtifactPublisher(storage)
            )
            processed = 0
            for _ in range(max_jobs):
                database.recover_expired_ai_job(
                    max_attempts=max_attempts, job_id=job_id
                )
                if not worker.process_one(job_id=job_id):
                    break
                processed += 1
            return processed
    finally:
        database.close()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--max-jobs", type=int, choices=range(1, 101), default=1)
    parser.add_argument("--max-attempts", type=int, choices=(1, 2, 3), default=1)
    parser.add_argument("--job-id", type=UUID, help="Claim only this queued job")
    args = parser.parse_args(argv)
    try:
        count = run_worker(
            BackendSettings(),
            max_jobs=args.max_jobs,
            max_attempts=args.max_attempts,
            job_id=args.job_id,
        )
        print(
            f"Processed {count} queue item(s). Check the job status API for outcomes."
        )
        return 0
    except KeyboardInterrupt:
        print("Worker interrupted; expired leases are recovered on the next run.")
        return 130
    except Exception as exc:
        print(
            f"Worker unavailable ({type(exc).__name__}); check local configuration.",
            file=sys.stderr,
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
