"""Verified rendered input and full-timeline PCM extraction."""

from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from uuid import UUID, uuid4

from intentcut.ai.voice import MAX_AUDIO_SECONDS, inspect_wav
from intentcut.backend.ai_job_service import AIJobAPIError, AIJobService
from intentcut.backend.contracts import AIProcessingError
from intentcut.backend.storage.database_models import AIJobArtifact
from intentcut.media.models import MediaMetadata
from intentcut.media.probe_parser import MediaProbe
from intentcut.media.process_runner import ProcessRunner


@contextmanager
def verified_video(
    jobs: AIJobService, project_id: UUID, artifact_id: UUID, max_seconds: int
) -> Iterator[tuple[AIJobArtifact, MediaMetadata, Path]]:
    artifact = jobs.database.get_project_artifact(project_id, artifact_id)
    if artifact is None or artifact.kind not in {"video", "rendition"}:
        raise AIJobAPIError(404, "not_found", "Video artifact not found.")
    with jobs.storage.staging() as batch:
        with jobs.snapshot(project_id, artifact) as snapshot:
            staged = jobs.storage.stage(snapshot, batch, uuid4())
        metadata = MediaProbe().probe(staged.path)
        if metadata.duration > min(max_seconds, MAX_AUDIO_SECONDS):
            raise AIProcessingError("processing_limit")
        yield artifact, metadata, staged.path


def extract_audio(
    source: Path, metadata: MediaMetadata, target: Path
) -> tuple[int, bool]:
    frames = round(metadata.duration * 24_000)
    if not 0 < frames <= MAX_AUDIO_SECONDS * 24_000:
        raise AIProcessingError("processing_limit")
    if metadata.audio is None:
        inputs = ["-f", "lavfi", "-i", "anullsrc=channel_layout=mono:sample_rate=24000"]
        filters = f"atrim=end_sample={frames}"
    else:
        inputs = [
            "-copyts",
            "-i",
            str(source),
            "-map",
            f"0:{metadata.audio.index}",
            "-vn",
        ]
        # Normalize to the VIDEO origin, never to the first speech/audio sample.
        # Preserve positive offsets and gaps as silence; pad the complete tail.
        filters = (
            f"asetpts=PTS-({metadata.video.start_time:.9f})/TB,"
            f"aresample=24000:async=1:first_pts=0,apad,atrim=end_sample={frames}"
        )
    ProcessRunner().run_ffmpeg(
        [
            *inputs,
            "-af",
            filters,
            "-ac",
            "1",
            "-ar",
            "24000",
            "-c:a",
            "pcm_s16le",
            "-map_metadata",
            "-1",
            "-f",
            "wav",
            "-n",
            str(target),
        ],
        duration=metadata.duration,
    )
    duration_ms, silent = inspect_wav(target)
    if abs(duration_ms - metadata.duration * 1000) > 1:
        raise AIProcessingError("source_unavailable")
    return duration_ms, silent
