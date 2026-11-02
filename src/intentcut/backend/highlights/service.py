"""Highlight admission, local discovery, and bounded clip preview."""

import shutil
import tempfile
from pathlib import Path
from uuid import UUID

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
from intentcut.backend.storage.database_models import AIJob, MediaAsset
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
        if body.max_candidates + 1 > settings.ai_max_inference_requests:
            raise AIJobAPIError(
                422, "processing_limit", "Candidate count exceeds inference budget."
            )
        try:
            fingerprints = {str(asset.id): fingerprint_source(self.storage, asset)}
        except (OSError, ValueError) as exc:
            raise AIJobAPIError(
                422, "source_unavailable", "Source media is unavailable."
            ) from exc
        return self.database.create_ai_job(
            project_id,
            {
                **body.model_dump(mode="json"),
                "pipeline_version": "highlight_v1",
                "source_sha256": fingerprints,
            },
        )

    def _verified_source(
        self, project_id: UUID, asset: MediaAsset, expected_sha256: str
    ) -> Path:
        """Stream the immutable source to a private temp file; caller deletes it."""
        tmp_root = self.storage.root / ".tmp"
        tmp_root.mkdir(mode=0o700, exist_ok=True)
        workdir = Path(tempfile.mkdtemp(dir=tmp_root))
        try:
            destination = workdir / "source"
            with (
                self.storage.open_object(
                    asset.storage_key, project_id, asset.id
                ) as stream,
                destination.open("xb") as out,
            ):
                shutil.copyfileobj(stream, out, 1024 * 1024)
            actual = fingerprint_source(self.storage, asset)
            if actual != expected_sha256:
                raise AIJobAPIError(
                    503, "source_unavailable", "Source media failed verification."
                )
            return destination
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
                return extract_window(
                    source,
                    source.parent / "preview.mp4",
                    start_seconds=start_seconds,
                    end_seconds=min(end_seconds, metadata.duration),
                    video_stream_index=metadata.video.index,
                    audio_stream_index=metadata.audio.index if metadata.audio else None,
                )
            except (MediaProcessError, ValueError, FileNotFoundError) as exc:
                raise AIJobAPIError(
                    503, "source_unavailable", "Preview extraction failed."
                ) from exc
        except BaseException:
            self._cleanup_source(source)
            raise

    def discard_preview(self, clip: Path) -> None:
        self._cleanup_source(clip)
