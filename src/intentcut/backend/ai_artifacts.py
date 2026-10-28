import hashlib
import json
import logging
import os
from collections.abc import Callable, Sequence
from pathlib import Path
from uuid import UUID, uuid4

from intentcut.backend.ai_processing_adapter import ProcessingResult
from intentcut.backend.database import CommitOutcomeUnknown, Database
from intentcut.backend.database_models import AIJobArtifact
from intentcut.backend.local_media_storage import (
    LocalMediaStorage,
    StagedFile,
    regular_source,
)
from intentcut.media.probe_parser import ProbeParser
from intentcut.media.process_runner import PROBE_TIMEOUT, ProcessRunner

logger = logging.getLogger(__name__)


class AIArtifactPublisher:

    def __init__(self, storage: LocalMediaStorage) -> None:
        self._storage = storage
        self._runner = ProcessRunner()

    def publish_and_complete(
        self,
        database: Database,
        project_id: UUID,
        job_id: UUID,
        lease_token: UUID,
        result: ProcessingResult,
        *,
        owns_lease: Callable[[], bool] = lambda: True,
    ) -> bool:
        if not all(
            isinstance(value, UUID) for value in (project_id, job_id, lease_token)
        ):
            raise ValueError("Artifact publication requires UUID ownership identifiers")
        published: list[Path] = []
        retain_files = False
        with self._storage.staging() as batch:
            try:
                prepared = [
                    self._prepare(project_id, job_id, kind, source, batch)
                    for kind, source in (
                        ("storyboard", result.storyboard_path),
                        ("video", result.staged_video_path),
                    )
                ]
                if not owns_lease():
                    return False
                for staged, artifact in prepared:
                    target = self._storage.publish(staged.path, project_id, artifact.id)
                    published.append(target)
                    # Verify the published bytes, not just the processor output.
                    with regular_source(target) as stream:
                        if (
                            os.fstat(stream.fileno()).st_size != artifact.size_bytes
                            or hashlib.file_digest(stream, "sha256").hexdigest()
                            != artifact.sha256
                        ):
                            raise ValueError("Published artifact checksum mismatch")
                    self._sync_directories(target.parent)
                if not owns_lease():
                    return False
                artifacts = [artifact for _, artifact in prepared]
                try:
                    completed = database.complete_ai_job_with_artifacts(
                        project_id, job_id, lease_token, artifacts
                    )
                except CommitOutcomeUnknown:
                    # An empty snapshot cannot exclude an in-flight COMMIT.
                    retain_files = True
                    if self._reconcile(database, project_id, job_id, artifacts):
                        return True
                    logger.error(
                        "Uncertain artifact commit; retain files: "
                        "job=%s artifact_ids=%s",
                        job_id,
                        [artifact.id for artifact in artifacts],
                    )
                    raise
                retain_files = completed
                return completed
            finally:
                if not retain_files:
                    for path in reversed(published):
                        try:
                            self._storage.remove_published(path)
                        except OSError:
                            logger.error(
                                "Artifact cleanup failed: id=%s", path.parent.name
                            )

    def _prepare(
        self, project_id: UUID, job_id: UUID, kind: str, source: Path, batch: Path
    ) -> tuple[StagedFile, AIJobArtifact]:
        artifact_id = uuid4()
        with regular_source(source) as stream:
            before = os.fstat(stream.fileno())
            # Bound work before hashing; stage also enforces the streaming limit.
            limit = self._storage.max_file_bytes
            if kind == "storyboard":
                limit = min(limit, 8 * 1024 * 1024)
            if not 0 < before.st_size <= limit:
                raise ValueError("Invalid artifact size")
            checksum = hashlib.file_digest(stream, "sha256").hexdigest()
            stream.seek(0)
            staged = self._storage.stage(stream, batch, artifact_id)
            after = os.fstat(stream.fileno())
            if (before.st_size, before.st_mtime_ns, before.st_ctime_ns) != (
                after.st_size,
                after.st_mtime_ns,
                after.st_ctime_ns,
            ):
                raise ValueError("Artifact source changed during staging")
        with regular_source(staged.path) as stream:
            if hashlib.file_digest(stream, "sha256").hexdigest() != checksum:
                raise ValueError("Staged artifact checksum mismatch")
            # Persist file data before making a durable directory entry.
            os.fsync(stream.fileno())
        if kind == "storyboard":
            with staged.path.open(encoding="utf-8") as stream:
                if not isinstance(json.load(stream), dict):
                    raise ValueError("Storyboard must be a JSON object")
        else:
            self._validate_video(staged.path)
        return staged, AIJobArtifact(
            id=artifact_id,
            job_id=job_id,
            kind=kind,
            storage_key=self._storage.storage_key(project_id, artifact_id),
            size_bytes=staged.size_bytes,
            sha256=checksum,
        )

    def _validate_video(self, path: Path) -> None:
        raw = self._runner.run(
            [
                "ffprobe",
                "-v",
                "error",
                "-show_streams",
                "-show_format",
                "-of",
                "json",
                str(path),
            ],
            timeout=PROBE_TIMEOUT,
        )
        metadata = ProbeParser().parse(raw, path)
        container = json.loads(raw).get("format", {})
        with path.open("rb") as stream:
            header = stream.read(8)
        if (
            header[4:8] != b"ftyp"
            or "mp4" not in container.get("format_name", "").split(",")
            or container.get("tags", {}).get("major_brand", "").strip() == "qt"
            or not metadata.video.codec
            or metadata.video.frame_rate <= 0
        ):
            raise ValueError("Artifact is not a valid MP4 video")
        self._runner.run_ffmpeg(
            ["-i", str(path), "-f", "null", "-"], duration=metadata.duration
        )

    def _sync_directories(self, directory: Path) -> None:
        # New artifact/project directories and the root's entries must reach disk.
        while True:
            descriptor = os.open(
                directory, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
            )
            try:
                os.fsync(descriptor)
            finally:
                os.close(descriptor)
            if directory == self._storage.root:
                break
            directory = directory.parent

    @staticmethod
    def _reconcile(
        database: Database,
        project_id: UUID,
        job_id: UUID,
        expected: Sequence[AIJobArtifact],
    ) -> bool:
        def identity(artifact: AIJobArtifact) -> tuple:
            return (
                artifact.id,
                artifact.job_id,
                artifact.kind,
                artifact.storage_key,
                artifact.size_bytes,
                artifact.sha256,
            )

        try:
            actual = database.list_ai_job_artifacts(project_id, job_id)
            job = database.get_ai_job(project_id, job_id)
            return (
                job is not None
                and job.status == "succeeded"
                and {identity(a) for a in actual} == {identity(a) for a in expected}
            )
        except Exception:
            return False
