import argparse
import sys
import time
from contextlib import nullcontext
from uuid import UUID

from openai import OpenAI

from intentcut.ai.muse import MuseClient
from intentcut.ai.voice import MuseVoiceClient
from intentcut.backend.ai_artifacts import AIArtifactPublisher
from intentcut.backend.ai_job_service import AIJobService
from intentcut.backend.ai_processing_adapter import RealAIProcessingAdapter
from intentcut.backend.ai_worker import AIJobWorker
from intentcut.backend.artifacts.derived import (
    CaptionArtifactResult,
    VideoRenditionResult,
)
from intentcut.backend.captions.processor import CaptionBurnProcessor
from intentcut.backend.contracts import ProcessingResult, ProposalResult
from intentcut.backend.editing.processor import ManualRenderProcessor
from intentcut.backend.editing.revisions import RevisionProcessor
from intentcut.backend.editing.service import EditingService
from intentcut.backend.first_cut.media_inputs import processing_available
from intentcut.backend.jobs.dispatch import JobDispatcher, JobRegistration, JobType
from intentcut.backend.shared.settings import BackendSettings
from intentcut.backend.storage.database import Database
from intentcut.backend.storage.local_media_storage import LocalMediaStorage
from intentcut.backend.transcription.processor import TranscriptionProcessor
from intentcut.backend.transcription.service import transcription_available


def run_worker(
    settings: BackendSettings,
    *,
    max_jobs: int = 1,
    max_attempts: int = 1,
    continuous: bool = False,
    poll_seconds: float = 3.0,
    job_id: UUID | None = None,
    manual_only: bool = False,
    voice_only: bool = False,
    captions_only: bool = False,
) -> int:
    if sum((manual_only, voice_only, captions_only)) > 1:
        raise ValueError("Worker modes are mutually exclusive")
    if voice_only and not transcription_available(settings):
        raise ValueError("Voice transcription is not configured")
    if (
        not manual_only
        and not voice_only
        and not captions_only
        and not processing_available(settings)
    ):
        raise ValueError("Uploaded-media processing is not configured")
    if not 1 <= max_jobs <= 100 or not 1 <= max_attempts <= 3:
        raise ValueError("Invalid worker budget")
    if not 0.5 <= poll_seconds <= 60:
        raise ValueError("Invalid worker polling interval")

    if continuous and job_id is not None:
        raise ValueError("Continuous worker cannot target a single job")
    database = Database.connect(settings.database_url.get_secret_value())
    try:
        storage = LocalMediaStorage(
            settings.media_root, settings.max_file_bytes, settings.copy_chunk_bytes
        )
        storage.initialize()
        context = (
            nullcontext(None)
            if manual_only or voice_only or captions_only
            else OpenAI(
                base_url="https://api.meta.ai/v1",
                api_key=settings.model_api_key.get_secret_value(),
                timeout=180.0,
                max_retries=0,
            )
        )
        with context as client:
            ai_processor = (
                None
                if manual_only or voice_only or captions_only
                else RealAIProcessingAdapter(
                    database=database,
                    storage=storage,
                    settings=settings,
                    muse=MuseClient(client),
                )
            )
            manual_processor = ManualRenderProcessor(database, storage, settings)
            revision_processor = (
                None
                if manual_only or voice_only or captions_only
                else RevisionProcessor(
                    EditingService(AIJobService(database, storage, settings)),
                    MuseClient(client),
                )
            )

            registrations = (
                []
                if voice_only or captions_only
                else [
                    JobRegistration(
                        JobType.MANUAL_RENDER, manual_processor, ProcessingResult
                    )
                ]
            )
            if not voice_only and not manual_only:
                registrations.append(
                    JobRegistration(
                        JobType.CAPTION_BURN,
                        CaptionBurnProcessor(AIJobService(database, storage, settings)),
                        VideoRenditionResult,
                    )
                )
            if (
                not manual_only
                and not captions_only
                and transcription_available(settings)
            ):
                voice = MuseVoiceClient(
                    settings.model_api_key, timeout=settings.voice_timeout_seconds
                )
                registrations.append(
                    JobRegistration(
                        JobType.CAPTION_TRANSCRIBE,
                        TranscriptionProcessor(
                            AIJobService(database, storage, settings), voice
                        ),
                        CaptionArtifactResult,
                    )
                )
            if ai_processor is not None:
                registrations.append(
                    JobRegistration(
                        JobType.UPLOADED_FIRST_CUT, ai_processor, ProcessingResult
                    )
                )
            if revision_processor is not None:
                registrations.append(
                    JobRegistration(
                        JobType.SEQUENCE_REVISION, revision_processor, ProposalResult
                    )
                )
            dispatcher = JobDispatcher(registrations)

            worker = AIJobWorker(
                database, dispatcher, artifact_publisher=AIArtifactPublisher(storage)
            )
            processed = 0

            while True:
                database.recover_expired_ai_job(
                    max_attempts=max_attempts,
                    job_id=job_id,
                    supported_job_types=dispatcher.supported_job_types,
                    **({"manual_only": True} if manual_only else {}),
                )

                claimed = worker.process_one(
                    job_id=job_id, **({"manual_only": True} if manual_only else {})
                )

                if claimed:
                    processed += 1

                    if not continuous and processed >= max_jobs:
                        break

                    continue

                # No queued job available.
                if not continuous:
                    break

                # Wait before checking PostgreSQL again.
                time.sleep(poll_seconds)

            return processed
    finally:
        database.close()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    modes = parser.add_mutually_exclusive_group()
    modes.add_argument(
        "--manual-only",
        action="store_true",
        help="Render edits without initializing an AI provider",
    )
    modes.add_argument(
        "--voice-only",
        action="store_true",
        help="Transcribe without initializing Muse Spark",
    )
    modes.add_argument(
        "--captions-only",
        action="store_true",
        help="Burn saved captions without any AI provider",
    )
    parser.add_argument("--max-jobs", type=int, choices=range(1, 101), default=1)
    parser.add_argument("--max-attempts", type=int, choices=(1, 2, 3), default=1)
    parser.add_argument("--job-id", type=UUID, help="Claim only this queued job")
    parser.add_argument(
        "--continuous",
        action="store_true",
        help="Keep polling PostgreSQL for queued jobs",
    )

    parser.add_argument(
        "--poll-seconds",
        type=float,
        default=3.0,
    )
    args = parser.parse_args(argv)
    try:
        count = run_worker(
            BackendSettings(),
            max_jobs=args.max_jobs,
            max_attempts=args.max_attempts,
            job_id=args.job_id,
            continuous=args.continuous,
            manual_only=args.manual_only,
            voice_only=args.voice_only,
            captions_only=args.captions_only,
            poll_seconds=args.poll_seconds,
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
