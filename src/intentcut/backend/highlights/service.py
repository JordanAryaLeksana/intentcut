"""Highlight admission, local discovery, and bounded clip preview."""

import hashlib
import os
import shutil
import stat
import tempfile
from pathlib import Path
from uuid import UUID, uuid4

from sqlalchemy import func, select

from intentcut.backend.ai_job_service import AIJobAPIError, AIJobService
from intentcut.backend.first_cut.media_inputs import (
    fingerprint_source,
    processing_available,
)
from intentcut.backend.highlights import discovery
from intentcut.backend.highlights.contracts import (
    CandidateListResponse,
    CandidateResponse,
    HighlightRequest,
)
from intentcut.backend.highlights.retrieval import (
    COARSE_SAMPLES,
    FINE_SAMPLES,
    MAX_RANK_CALLS,
)
from intentcut.backend.storage.database_models import AIJob, MediaAsset, Project
from intentcut.media.models import MediaProcessError
from intentcut.media.probe_parser import MediaProbe
from intentcut.media.window_extract import extract_window


class HighlightService:
    def __init__(self, jobs: AIJobService) -> None:
        self.jobs = jobs
        self.database = jobs.database
        self.storage = jobs.storage

    def _budgets(self):
        settings = self.jobs.settings
        if settings is None or not processing_available(settings):
            raise AIJobAPIError(
                503,
                "highlight_unavailable",
                "Highlight processing is not configured in this environment.",
            )
        return settings

    def _admit_asset(self, project_id: UUID, media_id: UUID) -> MediaAsset:
        settings = self._budgets()
        asset = self.database.get_media(project_id, media_id)
        if (
            not 0 < asset.size_bytes <= settings.highlight_max_source_bytes
            or not 0 < asset.duration_seconds <= settings.highlight_max_duration_seconds
            or max(asset.width, asset.height) > 4096
        ):
            raise AIJobAPIError(
                422, "processing_limit", "Media exceeds highlight processing limits."
            )
        return asset

    def create(self, project_id: UUID, body: HighlightRequest) -> AIJob:
        settings = self._budgets()
        self.database.require_project(project_id)
        asset = self._admit_asset(project_id, body.media_ids[0])
        if body.max_candidates > settings.ai_max_windows:
            raise AIJobAPIError(
                422, "processing_limit", "Candidate count exceeds window budget."
            )
        if (
            body.max_candidates + 1 + (0 if body.candidate_ids else MAX_RANK_CALLS)
            > settings.ai_max_inference_requests
            or (
                body.max_candidates * 5
                if body.candidate_ids
                else COARSE_SAMPLES + FINE_SAMPLES
            )
            > settings.highlight_max_probes
        ):
            raise AIJobAPIError(
                422, "processing_limit", "Candidate count exceeds inference budget."
            )
        try:
            fingerprints = {str(asset.id): fingerprint_source(self.storage, asset)}
        except (OSError, ValueError) as exc:
            raise AIJobAPIError(
                422, "source_unavailable", "Source media is unavailable."
            ) from exc
        payload = {
            **body.model_dump(mode="json", exclude_none=True),
            "pipeline_version": "highlight_v1",
            "source_sha256": fingerprints,
        }
        with self.database._sessions.begin() as session:
            session.scalar(
                select(Project).where(Project.id == project_id).with_for_update()
            )
            if body.request_id:
                existing = session.get(AIJob, body.request_id)
                if existing:
                    if (
                        existing.project_id != project_id
                        or existing.request_payload != payload
                    ):
                        raise AIJobAPIError(
                            409,
                            "request_conflict",
                            "Request identifier was already used.",
                        )
                    return existing
            predicate = (
                AIJob.project_id == project_id,
                AIJob.request_payload["pipeline_version"].astext == "highlight_v1",
            )
            # Recover an identical accepted request after a lost response or
            # refresh, even when the browser no longer has its request ID.
            signature = {k: v for k, v in payload.items() if k != "request_id"}
            for prior in session.scalars(
                select(AIJob).where(
                    *predicate, AIJob.status.in_(["queued", "running", "succeeded"])
                ).order_by(AIJob.created_at.desc())
            ):
                if {k: v for k, v in prior.request_payload.items() if k != "request_id"} == signature:
                    return prior
            if session.scalar(
                select(AIJob.id)
                .where(*predicate, AIJob.status.in_(["queued", "running"]))
                .limit(1)
            ):
                raise AIJobAPIError(
                    409, "highlight_pending", "A highlight job is already processing."
                )
            if (
                session.scalar(
                    select(func.count()).select_from(AIJob).where(*predicate)
                )
                >= settings.highlight_max_jobs_per_project
            ):
                raise AIJobAPIError(
                    422,
                    "processing_limit",
                    "This project's highlight job budget is exhausted.",
                )
            job = AIJob(
                id=body.request_id or uuid4(),
                project_id=project_id,
                request_payload=payload,
                status="queued",
            )
            session.add(job)
            session.flush()
            return job

    def _verified_source(
        self, project_id: UUID, asset: MediaAsset, expected_sha256: str
    ) -> Path:
        """Verify the immutable source and stage it without copying video bytes."""
        tmp_root = self.storage.root / ".tmp"
        tmp_root.mkdir(mode=0o700, exist_ok=True)
        workdir = Path(tempfile.mkdtemp(dir=tmp_root))

        try:
            destination = workdir / "source"

            with self.storage.open_object(
                asset.storage_key, project_id, asset.id
            ) as stream:
                before = os.fstat(stream.fileno())

                digest = hashlib.sha256()
                while chunk := stream.read(1024 * 1024):
                    digest.update(chunk)

                after = os.fstat(stream.fileno())

                if (
                    digest.hexdigest() != expected_sha256
                    or before.st_size != after.st_size
                    or before.st_mtime_ns != after.st_mtime_ns
                    or before.st_ino != after.st_ino
                    or before.st_dev != after.st_dev
                ):
                    raise AIJobAPIError(
                        503,
                        "source_unavailable",
                        "Source media failed verification.",
                    )

                # Both paths are under the same local storage filesystem.
                # Hard-linking avoids copying the entire multi-GB source.
                original = self.storage.root / asset.storage_key
                os.link(
                    original,
                    destination,
                    follow_symlinks=False,
                )

                linked = os.lstat(destination)

                # Reject symlinks and ensure the linked inode is exactly
                # the file verified through the secure storage descriptor.
                if (
                    not stat.S_ISREG(linked.st_mode)
                    or linked.st_dev != after.st_dev
                    or linked.st_ino != after.st_ino
                ):
                    raise AIJobAPIError(
                        503,
                        "source_unavailable",
                        "Source identity changed during staging.",
                    )

            return destination

        except OSError as exc:
            shutil.rmtree(workdir, ignore_errors=True)
            raise AIJobAPIError(
                503,
                "source_unavailable",
                "Source media could not be staged.",
            ) from exc

        except BaseException:
            shutil.rmtree(workdir, ignore_errors=True)
            raise
    def _cleanup_source(self, source: Path) -> None:
        shutil.rmtree(source.parent, ignore_errors=True)

    def candidates(
        self,
        project_id: UUID,
        media_id: UUID,
        *,
        candidate_seconds: float = 8.0,
        max_candidates: int = 8,
    ) -> CandidateListResponse:
        asset = self._admit_asset(project_id, media_id)
        try:
            digest = fingerprint_source(self.storage, asset)
        except (OSError, ValueError) as exc:
            raise AIJobAPIError(
                503, "source_unavailable", "Source media is unavailable."
            ) from exc
        source = self._verified_source(project_id, asset, digest)
        try:
            try:
                found = discovery.discover_candidates(
                    asset.duration_seconds,
                    str(asset.id),
                    lambda t: discovery.ffmpeg_probe(source, t),
                    candidate_seconds=candidate_seconds,
                    max_candidates=max_candidates,
                )
            except (MediaProcessError, ValueError) as exc:
                raise AIJobAPIError(
                    503, "discovery_failed", "Candidate discovery failed."
                ) from exc
        finally:
            self._cleanup_source(source)
        return CandidateListResponse(
            media_id=asset.id,
            duration_seconds=asset.duration_seconds,
            sha256=digest,
            candidates=[
                CandidateResponse(
                    id=c.id,
                    media_id=asset.id,
                    start_seconds=c.start_seconds,
                    end_seconds=c.end_seconds,
                    score=c.score,
                    components=dict(c.components),
                )
                for c in found
            ],
        )

    def preview_clip(
        self, project_id: UUID, media_id: UUID, start_seconds: float, end_seconds: float
    ) -> Path:
        """Extract one bounded candidate clip; caller deletes the directory."""
        settings = self._budgets()
        asset = self._admit_asset(project_id, media_id)
        if not (
            0 <= start_seconds < end_seconds <= asset.duration_seconds + 1e-6
            and end_seconds - start_seconds <= settings.highlight_preview_seconds
        ):
            raise AIJobAPIError(
                422, "invalid_range", "Preview range is outside the source media."
            )
        try:
            digest = fingerprint_source(self.storage, asset)
        except (OSError, ValueError) as exc:
            raise AIJobAPIError(
                503, "source_unavailable", "Source media is unavailable."
            ) from exc
        source = self._verified_source(project_id, asset, digest)
        try:
            probe = MediaProbe()
            try:
                metadata = probe.probe(source)
            except Exception as exc:
                raise AIJobAPIError(
                    503, "source_unavailable", "Source media is unavailable."
                ) from exc
            try:
                clip = extract_window(
                    source,
                    source.parent / "preview.mp4",
                    start_seconds=start_seconds,
                    end_seconds=min(end_seconds, metadata.duration),
                    video_stream_index=metadata.video.index,
                    audio_stream_index=metadata.audio.index if metadata.audio else None,
                )

                # The source copy is no longer needed after FFmpeg finishes.
                # Keep only the small preview MP4 for the HTTP response.
                source.unlink()

                return clip
            except (MediaProcessError, ValueError, FileNotFoundError) as exc:
                raise AIJobAPIError(
                    503, "source_unavailable", "Preview extraction failed."
                ) from exc
        except BaseException:
            self._cleanup_source(source)
            raise

    def discard_preview(self, clip: Path) -> None:
        self._cleanup_source(clip)
