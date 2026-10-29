"""Lease-aware execution and persistent completion of AI jobs."""

import logging
from collections.abc import Callable
from threading import Event, Thread
from uuid import UUID

from intentcut.backend.ai_artifacts import AIArtifactPublisher
from intentcut.backend.ai_processing_adapter import RealAIProcessingAdapter
from intentcut.backend.artifacts.derived import (
    DERIVED_RESULT_TYPES,
    CaptionArtifactResult,
    DerivedResult,
)
from intentcut.backend.contracts import (
    AIProcessingError,
    JobLeaseLost,
    ProcessingResult,
    ProposalResult,
)
from intentcut.backend.editing.processor import ManualRenderProcessor
from intentcut.backend.editing.revisions import RevisionProcessor
from intentcut.backend.jobs.dispatch import JobDispatcher, JobRegistration, JobType
from intentcut.backend.storage.database import CommitOutcomeUnknown, Database
from intentcut.backend.storage.database_models import AIJob
from intentcut.backend.transcription.processor import TranscriptionProcessor

logger = logging.getLogger(__name__)

JobProcessor = Callable[
    [AIJob], ProcessingResult | ProposalResult | DerivedResult | None
]


class AIJobWorker:
    def __init__(
        self,
        database: Database,
        processor: JobProcessor,
        *,
        artifact_publisher: AIArtifactPublisher | None = None,
        allow_artifact_free_processor: bool = False,
        lease_seconds: int = 300,
        heartbeat_interval_seconds: float = 15.0,
    ) -> None:
        if type(lease_seconds) is not int or not 1 <= lease_seconds <= 3600:
            raise ValueError("Invalid lease duration")
        if not 0 < heartbeat_interval_seconds < lease_seconds / 2:
            raise ValueError("Invalid heartbeat interval")
        if isinstance(processor, RealAIProcessingAdapter) and (
            artifact_publisher is None or allow_artifact_free_processor
        ):
            raise ValueError("Real processing requires artifact publication")
        # Preserve direct adapter construction used by existing callers, while
        # giving those production adapters the same capability fence as the CLI.
        if isinstance(processor, RealAIProcessingAdapter):
            processor = JobDispatcher(
                [
                    JobRegistration(
                        JobType.UPLOADED_FIRST_CUT, processor, ProcessingResult
                    )
                ]
            )
        elif isinstance(processor, ManualRenderProcessor):
            processor = JobDispatcher(
                [JobRegistration(JobType.MANUAL_RENDER, processor, ProcessingResult)]
            )
        elif isinstance(processor, RevisionProcessor):
            processor = JobDispatcher(
                [JobRegistration(JobType.SEQUENCE_REVISION, processor, ProposalResult)]
            )
        elif isinstance(processor, TranscriptionProcessor):
            processor = JobDispatcher(
                [
                    JobRegistration(
                        JobType.CAPTION_TRANSCRIBE, processor, CaptionArtifactResult
                    )
                ]
            )
        if isinstance(processor, JobDispatcher) and (
            allow_artifact_free_processor
            or (processor.requires_artifact_publisher and artifact_publisher is None)
        ):
            raise ValueError("Registered processing requires artifact publication")
        self._database = database
        self._processor = processor
        self._publisher = artifact_publisher
        # Explicit compatibility for synthetic processors only. A ProcessingResult
        # always requires publication, even when this option is enabled.
        self._allow_artifact_free = allow_artifact_free_processor
        self._lease_seconds = lease_seconds
        self._heartbeat_interval = heartbeat_interval_seconds

    @property
    def supported_job_types(self) -> tuple[str, ...] | None:
        if isinstance(self._processor, JobDispatcher):
            return self._processor.supported_job_types
        # Compatibility for injected synthetic processors; production CLI and
        # known production adapters always use the registry above.
        return None

    def process_one(
        self, *, job_id: UUID | None = None, manual_only: bool = False
    ) -> bool:
        """Claim, execute, publish, and finalize at most one job."""
        job = self._database.claim_next_ai_job(
            lease_seconds=self._lease_seconds,
            **({"job_id": job_id} if job_id is not None else {}),
            **({"manual_only": True} if manual_only else {}),
            **(
                {"supported_job_types": self.supported_job_types}
                if self.supported_job_types is not None
                else {}
            ),
        )
        if job is None:
            return False
        token = job.lease_token
        if token is None:
            raise RuntimeError("Claimed job has no lease token")

        stop_heartbeat = Event()
        ownership_lost = Event()

        def maintain_lease() -> None:
            while not stop_heartbeat.wait(self._heartbeat_interval):
                try:
                    renewed = self._database.heartbeat_ai_job(
                        project_id=job.project_id,
                        job_id=job.id,
                        lease_token=token,
                        lease_seconds=self._lease_seconds,
                    )
                except Exception as exc:
                    logger.error(
                        "Heartbeat failed for job %s (%s)", job.id, type(exc).__name__
                    )
                    ownership_lost.set()
                    return
                if not renewed:
                    ownership_lost.set()
                    return

        heartbeat = Thread(
            target=maintain_lease, name=f"ai-job-heartbeat-{job.id}", daemon=True
        )
        heartbeat.start()
        try:
            try:
                result = self._processor(job)
                if ownership_lost.is_set():
                    return True  # Recovery handles the expired lease.
                if isinstance(result, ProposalResult):
                    from intentcut.backend.editing.revisions import complete_proposal

                    completed = complete_proposal(self._database, job, result)
                elif isinstance(result, (ProcessingResult, *DERIVED_RESULT_TYPES)):
                    if self._publisher is None:
                        raise RuntimeError("Artifact publisher is required")
                    if not self._database.update_ai_job_progress(
                        job.project_id, job.id, token, "publishing_artifacts"
                    ):
                        raise JobLeaseLost("Artifact stage rejected by lease")
                    completed = self._publisher.publish_and_complete(
                        self._database,
                        job.project_id,
                        job.id,
                        token,
                        result,
                        owns_lease=lambda: not ownership_lost.is_set(),
                    )
                elif result is None and self._allow_artifact_free:
                    completed = self._database.complete_ai_job(
                        project_id=job.project_id, job_id=job.id, lease_token=token
                    )
                else:
                    raise TypeError("Processor must return required artifacts")
                if not completed:
                    logger.warning("AI job completion rejected by lease: %s", job.id)
            except JobLeaseLost:
                ownership_lost.set()
                logger.warning("AI job ownership lost: %s", job.id)
            except CommitOutcomeUnknown:
                # Do not fail or delete: COMMIT may already have succeeded.
                # Files remain for reconciliation; recovery handles a rolled-back job.
                logger.error("AI job completion outcome uncertain: %s", job.id)
            except Exception as exc:
                logger.error(
                    "AI job processing failed: job=%s type=%s",
                    job.id,
                    type(exc).__name__,
                )
                if not ownership_lost.is_set():
                    failed = self._database.fail_ai_job(
                        project_id=job.project_id,
                        job_id=job.id,
                        lease_token=token,
                        error_code=(
                            exc.code
                            if isinstance(exc, AIProcessingError)
                            else "processing_failed"
                        ),
                    )
                    if not failed:
                        logger.warning("Could not fail job; ownership lost: %s", job.id)
        finally:
            stop_heartbeat.set()
            heartbeat.join(timeout=15.0)
        return True
