"""Only canonical project-owned artifacts may become reference images."""

from collections.abc import Iterator
from contextlib import contextmanager
from uuid import UUID, uuid4

from intentcut.backend.ai_job_service import AIJobAPIError, AIJobService
from intentcut.backend.artifacts.derived import validate_image
from intentcut.media.probe_parser import MediaProbe
from intentcut.media.process_runner import ProcessRunner


@contextmanager
def authorized_source(
    jobs: AIJobService, project: UUID, identifier: UUID, frame_seconds: float | None
) -> Iterator[tuple]:
    artifact = jobs.database.get_project_artifact(project, identifier)
    if artifact is None or artifact.kind not in {"video", "rendition", "image"}:
        raise AIJobAPIError(404, "not_found", "Reference asset not found.")
    with jobs.storage.staging() as batch:
        with jobs.snapshot(project, artifact) as snapshot:
            staged = jobs.storage.stage(snapshot, batch, uuid4())
        if artifact.kind == "image":
            if frame_seconds is not None:
                raise AIJobAPIError(
                    422, "invalid_reference", "Images do not have video frames."
                )
            content_type = validate_image(staged.path, ProcessRunner())
            yield artifact, staged.path, content_type
        else:
            metadata = MediaProbe().probe(staged.path)
            if (
                frame_seconds is None
                or not 0 <= frame_seconds < metadata.duration
                or metadata.duration > 600
            ):
                raise AIJobAPIError(
                    422,
                    "invalid_reference",
                    "Choose a frame inside a video of at most ten minutes.",
                )
            if (
                metadata.video.width > 8192
                or metadata.video.height > 8192
                or metadata.video.width * metadata.video.height > 16_777_216
            ):
                raise AIJobAPIError(
                    422,
                    "invalid_reference",
                    "Video frame dimensions exceed reference limits.",
                )
            frame = batch / "reference.png"
            ProcessRunner().run_ffmpeg(
                [
                    "-ss",
                    f"{frame_seconds:.6f}",
                    "-i",
                    str(staged.path),
                    "-map",
                    f"0:{metadata.video.index}",
                    "-frames:v",
                    "1",
                    "-threads",
                    "1",
                    "-n",
                    str(frame),
                ],
                duration=metadata.duration,
            )
            content_type = validate_image(frame, ProcessRunner())
            yield artifact, frame, content_type
