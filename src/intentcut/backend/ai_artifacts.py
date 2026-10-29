from __future__ import annotations

from typing import TYPE_CHECKING

from intentcut.backend.shared.persistence_errors import CommitOutcomeUnknown

if TYPE_CHECKING:
    from intentcut.backend.storage.database import Database

import hashlib
import json
import logging
import os
from collections.abc import Callable, Sequence
from pathlib import Path
from uuid import UUID, uuid4

from intentcut.backend.artifacts.derived import (
    CAPTION_LIMIT,
    DERIVED_RESULT_TYPES,
    IMAGE_LIMIT,
    CaptionArtifactResult,
    DerivedResult,
    ImageArtifactResult,
    VideoRenditionResult,
    validate_caption,
    validate_image,
)
from intentcut.backend.contracts import ProcessingResult
from intentcut.backend.storage.database_models import AIJobArtifact
from intentcut.backend.storage.local_media_storage import (
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
        result: ProcessingResult | DerivedResult,
        *,
        owns_lease: Callable[[], bool] = lambda: True,
    ) -> bool:
        if not all(
            isinstance(value, UUID) for value in (project_id, job_id, lease_token)
        ):
            raise ValueError("Artifact publication requires UUID ownership identifiers")
        if type(result) not in (ProcessingResult, *DERIVED_RESULT_TYPES):
            raise ValueError("Unsupported result type")
        published: list[Path] = []
        retain_files = False
        with self._storage.staging() as batch:
            try:
                if isinstance(result, ProcessingResult):
                    sources = (
                        ("storyboard", result.storyboard_path),
                        ("video", result.staged_video_path),
                    )
                elif type(result) in DERIVED_RESULT_TYPES:
                    kind = {
                        CaptionArtifactResult: "captions",
                        ImageArtifactResult: "image",
                        VideoRenditionResult: "rendition",
                    }[type(result)]
                    parent_duration = self._validate_parent(
                        database, project_id, result, batch
                    )
                    sources = ((kind, result.path),)
                else:
                    raise ValueError("Unsupported result type")
                prepared = [
                    self._prepare(project_id, job_id, kind, source, batch)
                    for kind, source in sources
                ]
                if isinstance(result, CaptionArtifactResult):
                    document = validate_caption(prepared[0][0].path.read_bytes())
                    if (
                        parent_duration is None
                        or abs(document.duration_ms - parent_duration * 1000) > 50
                    ):
                        raise ValueError("Caption duration does not match parent")
                if (
                    isinstance(result, DERIVED_RESULT_TYPES)
                    and result.parent is not None
                ):
                    prepared[0][1].parent_artifact_id = result.parent.artifact_id
                    prepared[0][1].parent_sha256 = result.parent.sha256
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
                    if isinstance(result, ProcessingResult):
                        completed = database.complete_ai_job_with_artifacts(
                            project_id, job_id, lease_token, artifacts
                        )
                    else:
                        completed = database.complete_derived_artifact(
                            project_id, job_id, lease_token, artifacts[0]
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
        if kind not in {"video", "storyboard", "captions", "image", "rendition"}:
            raise ValueError("Unsupported artifact kind")
        artifact_id = uuid4()
        content_type = None
        with regular_source(source) as stream:
            before = os.fstat(stream.fileno())
            # Bound work before hashing; stage also enforces the streaming limit.
            limit = self._storage.max_file_bytes
            if kind == "storyboard":
                limit = min(limit, 8 * 1024 * 1024)
            if kind == "captions":
                limit = min(limit, CAPTION_LIMIT)
            elif kind == "image":
                limit = min(limit, IMAGE_LIMIT)
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
        elif kind == "captions":
            validate_caption(staged.path.read_bytes())
            content_type = "application/json"
        elif kind == "image":
            content_type = validate_image(staged.path, self._runner)
        elif kind in {"video", "rendition"}:
            self._validate_video(staged.path)
            if kind == "rendition":
                content_type = "video/mp4"
        return staged, AIJobArtifact(
            id=artifact_id,
            job_id=job_id,
            kind=kind,
            storage_key=self._storage.storage_key(project_id, artifact_id),
            size_bytes=staged.size_bytes,
            sha256=checksum,
            content_type=content_type,
        )

    def _validate_parent(
        self, database: Database, project_id: UUID, result: DerivedResult, batch: Path
    ) -> float | None:
        if result.parent is None:
            if not isinstance(result, ImageArtifactResult):
                raise ValueError("Parent is required")
            return
        parent = database.get_project_artifact(project_id, result.parent.artifact_id)
        allowed = (
            {"video", "rendition", "image"}
            if isinstance(result, ImageArtifactResult)
            else {"video", "rendition"}
        )
        if (
            parent is None
            or parent.sha256 != result.parent.sha256
            or parent.kind not in allowed
        ):
            raise ValueError("Invalid parent reference")
        # Securely open and copy a bounded parent before inspecting it. No worker-
        # supplied pathname or URL is used, and no DB transaction spans media I/O.
        with self._storage.open_object(
            parent.storage_key, project_id, parent.id
        ) as source:
            if (
                not 0 < parent.size_bytes <= self._storage.max_file_bytes
                or os.fstat(source.fileno()).st_size != parent.size_bytes
            ):
                raise ValueError("Invalid parent size")
            staged = self._storage.stage(source, batch, uuid4())
        with regular_source(staged.path) as source:
            if (
                staged.size_bytes != parent.size_bytes
                or hashlib.file_digest(source, "sha256").hexdigest() != parent.sha256
            ):
                raise ValueError("Parent checksum mismatch")
        if isinstance(result, CaptionArtifactResult):
            raw = self._runner.run(
                [
                    "ffprobe",
                    "-v",
                    "error",
                    "-show_streams",
                    "-show_format",
                    "-of",
                    "json",
                    str(staged.path),
                ],
                timeout=PROBE_TIMEOUT,
            )
            duration = ProbeParser().parse(raw, staged.path).duration
            return duration

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
                artifact.content_type,
                artifact.parent_artifact_id,
                artifact.parent_sha256,
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
