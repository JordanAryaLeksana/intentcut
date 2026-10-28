"""Uploaded media → grounded Muse evidence → validated EditPlan → M1A rendering."""

import math
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from intentcut.ai.story_director import build_edit_plan
from intentcut.ai.video_understanding import (
    Muse,
    PreparedWindow,
    WindowUnderstanding,
    file_digest,
)
from intentcut.backend.ai_jobs import AIProcessingError
from intentcut.backend.ai_media_inputs import (
    UploadedFirstCutRequest,
    fingerprint_source,
    plan_inputs,
)
from intentcut.backend.backend_settings import BackendSettings
from intentcut.backend.database import Database
from intentcut.backend.database_models import AIJob
from intentcut.backend.local_media_storage import LocalMediaStorage
from intentcut.media.probe_parser import MediaProbe
from intentcut.media.render import VerticalVideoRenderer
from intentcut.media.settings import FPS
from intentcut.media.window_extract import extract_window


@dataclass(frozen=True)
class ProcessingResult:
    storyboard_path: Path
    staged_video_path: Path


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
            raise RuntimeError("Job lease is no longer owned")

    def __call__(self, job: AIJob) -> ProcessingResult:
        request = UploadedFirstCutRequest.model_validate(job.request_payload)
        self._check_lease(job)
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

        try:
            windows = [
                understanding.analyze(p, cache, before_inference) for p in prepared
            ]
            before_inference()
            selection = self.muse.select(
                [w.public_evidence() for w in windows],
                request.intent,
                request.target_seconds,
            )
            edit_plan = build_edit_plan(
                selection, windows, request.media_ids, request.target_seconds
            )
        except AIProcessingError:
            raise
        except (ValueError, KeyError, TypeError) as exc:
            raise AIProcessingError("invalid_ai_selection") from exc
        except Exception as exc:
            raise AIProcessingError("provider_unavailable") from exc
        self._check_lease(job)
        by_index = {w.window_index: w for w in windows}
        selected = [by_index[cut.window_index] for cut in edit_plan.cuts]
        for window in selected:
            if file_digest(window.clip) != window.sha256:
                raise AIProcessingError("source_unavailable")
        output = workspace / "first_cut.mp4"
        result = VerticalVideoRenderer().render([w.clip for w in selected], output)
        if abs(result.intended_duration - edit_plan.render_seconds) > 1e-6:
            raise AIProcessingError("source_unavailable")
        self._check_lease(job)
        storyboard = workspace / "storyboard.json"
        with storyboard.open("x", encoding="utf-8") as stream:
            stream.write(edit_plan.model_dump_json(indent=2))
        return ProcessingResult(storyboard, output)
