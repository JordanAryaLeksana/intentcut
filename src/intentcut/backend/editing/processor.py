"""Re-extract only authorized published ranges, render without any AI calls."""

import json
from uuid import UUID

from intentcut.ai.story_director import EditPlan
from intentcut.backend.ai_job_service import AIJobService
from intentcut.backend.contracts import (
    AIProcessingError,
    JobLeaseLost,
    ProcessingResult,
)
from intentcut.backend.editing.service import EditingService
from intentcut.backend.first_cut.media_inputs import fingerprint_source
from intentcut.media.probe_parser import MediaProbe
from intentcut.media.render import VerticalVideoRenderer
from intentcut.media.settings import FPS
from intentcut.media.window_extract import extract_window


class ManualRenderProcessor:
    def __init__(self, database, storage, settings):
        self.database, self.storage, self.settings = database, storage, settings

    def __call__(self, job):
        def progress(stage):
            if not self.database.update_ai_job_progress(
                job.project_id, job.id, job.lease_token, stage
            ):
                raise JobLeaseLost("Manual render lease lost")

        progress("preparing_media")
        payload = job.request_payload
        plan = EditPlan.model_validate(payload["edit_plan"])
        service = EditingService(
            AIJobService(self.database, self.storage, self.settings)
        )
        # Revalidate the immutable base independently of the mutable head.
        _, allowed, _ = service.resolve(
            job.project_id,
            UUID(payload["base_job_id"]),
            UUID(payload["base_artifact_id"]),
            [c.window_index for c in plan.cuts],
        )
        if any(
            (c.media_id, c.start_seconds, c.end_seconds)
            != (a.media_id, a.start_seconds, a.end_seconds)
            for c, a in zip(plan.cuts, allowed, strict=True)
        ):
            raise AIProcessingError("source_unavailable")
        workspace = self.storage.job_workspace(
            job.id, job.attempt_count, job.lease_token
        )
        sources = {}
        probe = MediaProbe()
        for cut in plan.cuts:
            if cut.media_id in sources:
                continue
            asset = self.database.get_media(job.project_id, cut.media_id)
            path = workspace / f"source_{asset.id}"
            with path.open("xb") as stream:
                digest = fingerprint_source(self.storage, asset, stream)
            if digest != payload["source_sha256"].get(str(asset.id)):
                raise AIProcessingError("source_unavailable")
            sources[asset.id] = (path, probe.probe(path))
        progress("extracting_windows")
        clips = []
        for index, cut in enumerate(plan.cuts):
            progress("extracting_windows")
            path, metadata = sources[cut.media_id]
            clips.append(
                extract_window(
                    path,
                    workspace / f"cut_{index}.mp4",
                    start_seconds=cut.start_seconds,
                    end_seconds=cut.end_seconds,
                    video_stream_index=metadata.video.index,
                    audio_stream_index=metadata.audio.index if metadata.audio else None,
                )
            )
        progress("rendering_video")
        output = workspace / "manual.mp4"
        result = VerticalVideoRenderer().render(clips, output, measure_frames=True)
        if result.intended_duration > plan.target_seconds + 1e-6:
            raise AIProcessingError("processing_limit")
        position = 0
        manifest_cuts = []
        for cut, count in zip(plan.cuts, result.segment_frames, strict=True):
            manifest_cuts.append(
                {
                    **cut.model_dump(mode="json", exclude={"editorial_reason"}),
                    "output_start_frame": position,
                    "output_end_frame": position + count,
                }
            )
            position += count
        manifest = {
            "fps": FPS,
            "total_frames": position,
            "draft_revision": payload["draft_revision"],
            "base_job_id": payload["base_job_id"],
            "base_artifact_id": payload["base_artifact_id"],
            "cuts": manifest_cuts,
        }
        storyboard = workspace / "storyboard.json"
        with storyboard.open("x") as stream:
            json.dump(
                {
                    **plan.model_dump(mode="json"),
                    "render_seconds": position / FPS,
                    "render_manifest": manifest,
                },
                stream,
            )
        return ProcessingResult(storyboard, output)
