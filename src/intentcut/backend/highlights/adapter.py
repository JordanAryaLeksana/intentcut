"""Highlight pipeline: deferred discovery planning over one long-form source.

Reuses the entire first-cut worker path (staging, verification, window
extraction, grounded understanding, Story Director, EditPlan, FFmpeg render).
Only planning differs: instead of covering short clips end-to-end, candidate
moments are discovered across the full source timeline and each candidate
becomes one window at its ORIGINAL offsets. Muse still selects window indices
only, so timestamps stay server-grounded.
"""

from intentcut.ai.temporal_windows import TemporalWindow
from intentcut.backend.ai_processing_adapter import RealAIProcessingAdapter
from intentcut.backend.contracts import AIProcessingError
from intentcut.backend.highlights import discovery
from intentcut.backend.highlights.contracts import UploadedHighlightRequest
from intentcut.media.models import MediaProcessError


class HighlightProcessingAdapter(RealAIProcessingAdapter):
    def _admit_request(self, job) -> UploadedHighlightRequest:
        return UploadedHighlightRequest.model_validate(job.request_payload)

    def _plan_inputs(self, job, assets, request) -> None:
        # Metadata-only budget fence; content discovery needs staged sources.
        del job
        settings = self.settings
        if (
            len(assets) != 1
            or sum(a.size_bytes for a in assets) > settings.highlight_max_source_bytes
            or not 0
            < assets[0].duration_seconds
            <= settings.highlight_max_duration_seconds
            or request.max_candidates > settings.ai_max_windows
            or request.max_candidates + 1 > settings.ai_max_inference_requests
            or request.max_candidates * 5 > settings.highlight_max_probes
        ):
            raise AIProcessingError("processing_limit")
        return None

    def _plan_from_staged(self, job, request, sources) -> list:
        plans = []
        for asset, _, _, source, _, _ in sources:
            self._check_lease(job)
            try:
                found = discovery.discover_candidates(
                    asset.duration_seconds,
                    str(asset.id),
                    lambda t, _source=source: discovery.ffmpeg_probe(_source, t),
                    candidate_seconds=request.candidate_seconds,
                    max_candidates=request.max_candidates,
                )
            except (MediaProcessError, ValueError) as exc:
                raise AIProcessingError("processing_failed") from exc
            if request.candidate_ids is not None:
                wanted = set(request.candidate_ids)
                found = [c for c in found if c.id in wanted]
            if not found:
                raise AIProcessingError("processing_failed")
            plans.append(
                [
                    TemporalWindow(
                        index=index,
                        start_seconds=c.start_seconds,
                        end_seconds=c.end_seconds,
                    )
                    for index, c in enumerate(found)
                ]
            )
        if sum(map(len, plans)) > self.settings.ai_max_windows:
            raise AIProcessingError("processing_limit")
        if sum(map(len, plans)) + 1 > self.settings.ai_max_inference_requests:
            raise AIProcessingError("processing_limit")
        return plans
