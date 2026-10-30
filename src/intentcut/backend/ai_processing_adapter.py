"""Uploaded media → grounded Muse evidence → validated EditPlan → M1A rendering."""

import logging
import math
import traceback
from datetime import UTC, datetime

from intentcut.ai.story_director import build_edit_plan
from intentcut.ai.video_understanding import (
    Muse,
    PreparedWindow,
    WindowUnderstanding,
    file_digest,
)
from intentcut.backend.contracts import (
    AIProcessingError,
    JobLeaseLost,
    ProcessingResult,
)
from intentcut.backend.first_cut.contracts import UploadedFirstCutRequest
from intentcut.backend.first_cut.media_inputs import (
    fingerprint_source,
    plan_inputs,
)
from intentcut.backend.jobs.progress import ProgressStage
from intentcut.backend.shared.settings import BackendSettings
from intentcut.backend.storage.database import Database
from intentcut.backend.storage.database_models import AIJob
from intentcut.backend.storage.local_media_storage import LocalMediaStorage
from intentcut.media.probe_parser import MediaProbe
from intentcut.media.render import VerticalVideoRenderer
from intentcut.media.settings import FPS
from intentcut.media.window_extract import extract_window

logger = logging.getLogger(__name__)


class RealAIProcessingAdapter:
    def __init__(
        self,
        *,
        database: Database,
        storage: LocalMediaStorage,
        settings: BackendSettings,
        muse: Muse,
    ) -> None:
        self.database = database
        self.storage = storage
        self.settings = settings
        self.muse = muse

    def _check_lease(self, job: AIJob) -> None:
        current = self.database.get_ai_job(job.project_id, job.id)
        if (
            current is None
            or current.status != "running"
            or current.lease_token != job.lease_token
            or current.lease_expires_at is None
            or current.lease_expires_at <= datetime.now(UTC)
        ):
            raise JobLeaseLost("Job lease is no longer owned")

    def _progress(
        self,
        job: AIJob,
        stage: ProgressStage,
        *,
        completed_windows: int | None = None,
        total_windows: int | None = None,
    ) -> None:
        try:
            updated = self.database.update_ai_job_progress(
                job.project_id,
                job.id,
                job.lease_token,
                stage,
                completed_windows=completed_windows,
                total_windows=total_windows,
            )
        except Exception as exc:
            # A persistence failure must not be mistaken for a provider outage
            # by the inference exception boundary below.
            raise AIProcessingError("processing_failed") from exc
        if not updated:
            raise JobLeaseLost("Job progress rejected by lease")

    def __call__(self, job: AIJob) -> ProcessingResult:
        request = UploadedFirstCutRequest.model_validate(job.request_payload)
        self._check_lease(job)
        self._progress(job, "preparing_media")
        assets = [
            self.database.get_media(job.project_id, mid) for mid in request.media_ids
        ]
        plans = plan_inputs(assets, request.target_seconds, self.settings)
        workspace = self.storage.job_workspace(
            job.id, job.attempt_count, job.lease_token
        )
        cache = self.storage.job_cache(job.id)
        probe = MediaProbe()
        prepared = []
        sources = []
        remote_bytes = 0
        # Prepare and validate ALL sources/windows before spending on inference.
        for asset, plan in zip(assets, plans, strict=True):
            self._check_lease(job)
            directory = workspace / str(asset.id)
            directory.mkdir(mode=0o700)
            source = directory / "source"
            with source.open("xb") as stream:
                digest = fingerprint_source(self.storage, asset, stream)
            if digest != request.source_sha256[str(asset.id)]:
                raise AIProcessingError("source_unavailable")
            try:
                metadata = probe.probe(source)
                if abs(metadata.duration - asset.duration_seconds) > 1e-6 or (
                    metadata.video.width,
                    metadata.video.height,
                ) != (asset.width, asset.height):
                    raise ValueError("Source metadata changed")
            except Exception as exc:
                raise AIProcessingError("source_unavailable") from exc
            sources.append((asset, plan, directory, source, digest, metadata))

        self._progress(job, "extracting_windows")
        for asset, plan, directory, source, digest, metadata in sources:
            for window in plan:
                self._check_lease(job)
                clip = extract_window(
                    source,
                    directory / f"window_{window.index:03d}.mp4",
                    start_seconds=window.start_seconds,
                    end_seconds=window.end_seconds,
                    video_stream_index=metadata.video.index,
                    audio_stream_index=metadata.audio.index if metadata.audio else None,
                )
                size = clip.stat().st_size
                remote_bytes += size
                if (
                    not 0 < size <= self.settings.ai_max_remote_file_bytes
                    or remote_bytes > self.settings.ai_max_remote_total_bytes
                ):
                    raise AIProcessingError("processing_limit")
                actual = probe.probe(clip)
                if abs(actual.duration - window.duration_seconds) > 0.1:
                    raise AIProcessingError("source_unavailable")
                prepared.append(
                    PreparedWindow(
                        media_id=asset.id,
                        index=len(prepared),
                        window=window,
                        source_sha256=digest,
                        clip=clip,
                        sha256=file_digest(clip),
                        render_seconds=math.ceil(actual.duration * FPS - 1e-7) / FPS,
                    )
                )
        if not any(p.render_seconds <= request.target_seconds + 1e-6 for p in prepared):
            raise AIProcessingError("processing_limit")
        understanding = WindowUnderstanding(self.muse)
        new_calls = sum(
            not understanding.cache_path(p, cache).exists() for p in prepared
        )
        if new_calls + 1 > self.settings.ai_max_inference_requests:
            raise AIProcessingError("processing_limit")
        requests = 0

        def before_inference() -> None:
            nonlocal requests
            self._check_lease(job)
            requests += 1
            if requests > self.settings.ai_max_inference_requests:
                raise AIProcessingError("processing_limit")

        stage = "window_understanding"

        try:
            self._progress(
                job,
                "understanding_footage",
                completed_windows=0,
                total_windows=len(prepared),
            )
            windows = []
            for prepared_window in prepared:
                self._check_lease(job)
                evidence = understanding.analyze(
                    prepared_window, cache, before_inference
                )
                windows.append(evidence)
                # Cache hits and fresh inference count only after full validation.
                self._progress(
                    job,
                    "understanding_footage",
                    completed_windows=len(windows),
                    total_windows=len(prepared),
                )

            stage = "story_selection"

            before_inference()
            self._progress(job, "selecting_story")

            selection = self.muse.select(
                [w.public_evidence() for w in windows],
                request.intent,
                request.target_seconds,
            )

            stage = "edit_plan"

            edit_plan = build_edit_plan(
                selection,
                windows,
                request.media_ids,
                request.target_seconds,
            )

        except (AIProcessingError, JobLeaseLost):
            raise

        except (ValueError, KeyError, TypeError) as exc:
            logger.error(
                "AI selection error: stage=%s exception=%s",
                stage,
                type(exc).__name__,
            )
            raise AIProcessingError("invalid_ai_selection") from exc

        except Exception as exc:
            frames = traceback.extract_tb(exc.__traceback__)
            origin = frames[-1] if frames else None

            logger.error(
                "AI processing error: "
                "stage=%s exception=%s "
                "file=%s line=%s function=%s "
                "status=%s cause=%s",
                stage,
                type(exc).__name__,
                origin.filename.rsplit("/", 1)[-1] if origin else None,
                origin.lineno if origin else None,
                origin.name if origin else None,
                getattr(exc, "status_code", None),
                type(exc.__cause__).__name__ if exc.__cause__ else None,
            )

            raise AIProcessingError("provider_unavailable") from exc
        self._check_lease(job)
        by_index = {w.window_index: w for w in windows}
        selected = [by_index[cut.window_index] for cut in edit_plan.cuts]
        for window in selected:
            if file_digest(window.clip) != window.sha256:
                raise AIProcessingError("source_unavailable")
        output = workspace / "first_cut.mp4"
        self._progress(job, "rendering_video")
        result = VerticalVideoRenderer().render([w.clip for w in selected], output)
        if abs(result.intended_duration - edit_plan.render_seconds) > 1e-6:
            raise AIProcessingError("source_unavailable")
        self._check_lease(job)
        storyboard = workspace / "storyboard.json"
        with storyboard.open("x", encoding="utf-8") as stream:
            stream.write(edit_plan.model_dump_json(indent=2))
        return ProcessingResult(storyboard, output)
