"""Highlight pipeline: deferred discovery planning over one long-form source.

Reuses the entire first-cut worker path (staging, verification, window
extraction, grounded understanding, Story Director, EditPlan, FFmpeg render).
Only planning differs: instead of covering short clips end-to-end, candidate
moments are discovered across the full source timeline and each candidate
becomes one window at its ORIGINAL offsets. Muse still selects window indices
only, so timestamps stay server-grounded.
"""

import json

from intentcut.ai.temporal_windows import TemporalWindow
from intentcut.backend.ai_processing_adapter import RealAIProcessingAdapter
from intentcut.backend.contracts import AIProcessingError
from intentcut.backend.highlights import discovery
from intentcut.backend.highlights.contracts import UploadedHighlightRequest
from intentcut.backend.highlights.retrieval import (
    COARSE_SAMPLES,
    FINE_SAMPLES,
    MAX_RANK_CALLS,
    retrieve,
)
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
            or request.max_candidates
            + 1
            + (0 if request.candidate_ids else MAX_RANK_CALLS)
            > settings.ai_max_inference_requests
            or (
                request.max_candidates * 5
                if request.candidate_ids
                else COARSE_SAMPLES + FINE_SAMPLES
            )
            > settings.highlight_max_probes
        ):
            raise AIProcessingError("processing_limit")
        return None

    def _plan_from_staged(self, job, request, sources) -> list:
        plans = []
        retrieval_calls = 0
        retrieval_bytes = 0
        for asset, _, directory, source, _, metadata in sources:
            self._check_lease(job)
            try:
                if request.candidate_ids is not None:
                    found = discovery.discover_candidates(
                        asset.duration_seconds,
                        str(asset.id),
                        lambda t, _source=source: discovery.ffmpeg_probe(_source, t),
                        candidate_seconds=request.candidate_seconds,
                        max_candidates=request.max_candidates,
                    )
                else:

                    def before_call(total_bytes):
                        nonlocal retrieval_calls
                        self._check_lease(job)
                        retrieval_calls += 1
                        if (
                            retrieval_calls + request.max_candidates + 1
                            > self.settings.ai_max_inference_requests
                            or total_bytes > self.settings.ai_max_remote_total_bytes
                        ):
                            raise AIProcessingError("processing_limit")

                    found, retrieval_bytes, report = retrieve(
                        source,
                        directory / "retrieval",
                        asset.duration_seconds,
                        str(asset.id),
                        request.intent,
                        min(request.candidate_seconds, request.target_seconds),
                        request.max_candidates,
                        self.muse,
                        before_call,
                        lambda: self._check_lease(job),
                        lambda stage: self._progress(job, stage),
                        metadata.video.index,
                    )
                    report["candidates"] = [
                        {
                            "id": c.id,
                            "media_id": c.media_id,
                            "start_seconds": c.start_seconds,
                            "end_seconds": c.end_seconds,
                            "score": c.score,
                        }
                        for c in found
                    ]
                    (directory.parent / "highlight-discovery.json").write_text(
                        json.dumps(report)
                    )
            except AIProcessingError:
                raise
            except (ValueError, KeyError, TypeError) as exc:
                raise AIProcessingError("invalid_ai_selection") from exc
            except MediaProcessError as exc:
                raise AIProcessingError("source_unavailable") from exc
            except Exception as exc:
                from intentcut.backend.contracts import JobLeaseLost

                if isinstance(exc, JobLeaseLost):
                    raise
                raise AIProcessingError("provider_unavailable") from exc
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
        return plans, retrieval_calls, retrieval_bytes

    def __call__(self, job):
        result = super().__call__(job)
        report = result.storyboard_path.parent / "highlight-discovery.json"
        if report.exists():
            value = json.loads(result.storyboard_path.read_text())
            value["highlight_discovery"] = json.loads(report.read_text())
            result.storyboard_path.write_text(json.dumps(value))
        return result
