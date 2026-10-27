
import logging
from collections.abc import Callable
from threading import Event, Thread

from intentcut.backend.ai_processing_adapter import ProcessingResult
from intentcut.backend.database import Database
from intentcut.backend.database_models import AIJob

logger = logging.getLogger(__name__)

JobProcessor = Callable[[AIJob], ProcessingResult | None]


class AIJobWorker:
    def __init__(
        self,
        database: Database,
        processor: JobProcessor,
        *,
        lease_seconds: int = 300,
        heartbeat_interval_seconds: float = 15.0,
    ) -> None:
        if (
            type(lease_seconds) is not int
            or not 1 <= lease_seconds <= 3600
        ):
            raise ValueError("Invalid lease duration")

        if not 0 < heartbeat_interval_seconds < lease_seconds / 2:
            raise ValueError("Invalid heartbeat interval")

        self._database = database
        self._processor = processor
        self._lease_seconds = lease_seconds
        self._heartbeat_interval = heartbeat_interval_seconds

    def process_one(self) -> bool:
        """Claim, execute, and finalize at most one job."""

        job = self._database.claim_next_ai_job(
            lease_seconds=self._lease_seconds,
        )

        if job is None:
            return False

        token = job.lease_token

        if token is None:
            raise RuntimeError("Claimed job has no lease token")

        stop_heartbeat = Event()
        ownership_lost = Event()

        def maintain_lease() -> None:
            while not stop_heartbeat.wait(
                self._heartbeat_interval
            ):
                try:
                    renewed = self._database.heartbeat_ai_job(
                        project_id=job.project_id,
                        job_id=job.id,
                        lease_token=token,
                        lease_seconds=self._lease_seconds,
                    )
                except Exception as exc:
                    logger.error(
                        "Heartbeat failed for job %s (%s)",
                        job.id,
                        type(exc).__name__,
                    )
                    ownership_lost.set()
                    return

                if not renewed:
                    ownership_lost.set()
                    return

        heartbeat = Thread(
            target=maintain_lease,
            name=f"ai-job-heartbeat-{job.id}",
            daemon=True,
        )
        heartbeat.start()

        result = None
        processing_error = None

        try:
            result = self._processor(job)

            if result is not None:
                if not isinstance(result, ProcessingResult):
                    raise TypeError("Invalid processor result")

                if not result.storyboard_path.is_file():
                    raise RuntimeError("Storyboard artifact missing")

                video = result.staged_video_path

                if not video.is_file() or video.stat().st_size == 0:
                    raise RuntimeError("Video artifact missing")

        except Exception as exc:
            processing_error = exc

        finally:
            stop_heartbeat.set()
            heartbeat.join(timeout=15.0)

        if heartbeat.is_alive() or ownership_lost.is_set():
            logger.warning(
                "AI job ownership uncertain or lost: %s",
                job.id,
            )
            # Do not publish or complete; recovery handles expiry.
            return True

        if processing_error is not None:
            logger.error(
                "AI job processing failed: job=%s type=%s",
                job.id,
                type(processing_error).__name__,
            )

            failed = self._database.fail_ai_job(
                project_id=job.project_id,
                job_id=job.id,
                lease_token=token,
                error_code="processing_failed",
            )

            if not failed:
                logger.warning(
                    "Could not fail job; ownership lost: %s",
                    job.id,
                )

            return True

        completed = self._database.complete_ai_job(
            project_id=job.project_id,
            job_id=job.id,
            lease_token=token,
        )

        if not completed:
            raise RuntimeError(
                "AI job completion rejected by lease fencing"
            )

        return True
