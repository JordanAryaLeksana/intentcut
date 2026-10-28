"""Coordinate a complete upload batch and compensate known failures."""

import logging
import subprocess
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import BinaryIO
from uuid import UUID, uuid4

from sqlalchemy.exc import SQLAlchemyError

from intentcut.backend.storage.database import CommitOutcomeUnknown, Database
from intentcut.backend.storage.database_models import MediaAsset
from intentcut.backend.storage.local_media_storage import (
    EmptyFile,
    FileTooLarge,
    LocalMediaStorage,
    StagedFile,
)
from intentcut.media.models import InvalidMediaError, MediaMetadata, MediaProcessError
from intentcut.media.probe_parser import MediaProbe

# Preserve the logger name while existing imports transition to this package.
logger = logging.getLogger("intentcut.backend.media_ingestion_service")


class IngestionError(Exception):
    """Safe domain error; the HTTP layer chooses the status code."""

    def __init__(self, code: str, message: str, file_index: int | None = None) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.file_index = file_index


@dataclass(frozen=True)
class UploadSource:
    """A borrowed stream: the HTTP adapter owns and eventually closes it."""

    filename: str
    stream: BinaryIO


class MediaIngestionService:
    """Keep DB transactions short; accept a batch only after all files pass probing."""

    def __init__(
        self,
        database: Database,
        storage: LocalMediaStorage,
        probe: MediaProbe,
        max_files: int,
    ) -> None:
        self._database = database
        self._storage = storage
        self._probe = probe
        self._max_files = max_files

    def ingest(
        self, project_id: UUID, uploads: Sequence[UploadSource]
    ) -> list[MediaAsset]:
        self._database.require_project(project_id)
        if not uploads:
            raise IngestionError("invalid_upload", "At least one file is required.")
        if len(uploads) > self._max_files:
            raise IngestionError("upload_limit", "Too many uploaded files.")
        published: list[Path] = []
        retain_files = False
        with self._storage.staging() as batch:
            try:
                prepared = [
                    self._prepare(project_id, upload, batch, index)
                    for index, upload in enumerate(uploads)
                ]
                assets = [asset for _, asset in prepared]
                for staged, asset in prepared:
                    published.append(
                        self._storage.publish(staged.path, project_id, asset.id)
                    )
                try:
                    result = self._database.save_media_assets(project_id, assets)
                except CommitOutcomeUnknown:
                    # A lost COMMIT acknowledgement must never trigger file deletion.
                    retain_files = True
                    result = self._reconcile(assets)
                retain_files = True
                return result
            finally:
                if not retain_files:
                    for path in reversed(published):
                        try:
                            self._storage.remove_published(path)
                        except OSError:
                            logger.exception("Published-file cleanup failed: %s", path)

    def _prepare(
        self, project_id: UUID, upload: UploadSource, batch: Path, index: int
    ) -> tuple[StagedFile, MediaAsset]:
        filename = self._display_filename(upload.filename, index)
        media_id = uuid4()
        try:
            staged = self._storage.stage(upload.stream, batch, media_id)
        except FileTooLarge as exc:
            raise IngestionError(
                "upload_limit", "File exceeds the size limit.", index
            ) from exc
        except EmptyFile as exc:
            raise IngestionError(
                "invalid_media", "Uploaded file is empty.", index
            ) from exc
        try:
            metadata = self._probe.probe(staged.path)
        except InvalidMediaError as exc:
            raise IngestionError(
                "invalid_media", "File has no usable video metadata.", index
            ) from exc
        except MediaProcessError as exc:
            if isinstance(exc.__cause__, subprocess.CalledProcessError):
                raise IngestionError(
                    "invalid_media", "File could not be read as video.", index
                ) from exc
            raise IngestionError(
                "probe_unavailable", "Media inspection is unavailable.", index
            ) from exc
        return staged, self._record(project_id, media_id, filename, staged, metadata)

    @staticmethod
    def _display_filename(filename: str, index: int) -> str:
        # Names remain display-only, including when a client sends Windows paths.
        name = filename.replace("\\", "/").rsplit("/", 1)[-1]
        name = "".join(
            character for character in name if character.isprintable()
        ).strip()
        if not name or name in {".", ".."} or len(name) > 255:
            raise IngestionError("invalid_upload", "Invalid display filename.", index)
        return name

    def _record(
        self,
        project_id: UUID,
        media_id: UUID,
        filename: str,
        staged: StagedFile,
        metadata: MediaMetadata,
    ) -> MediaAsset:
        video, audio = metadata.video, metadata.audio
        return MediaAsset(
            id=media_id,
            project_id=project_id,
            original_filename=filename,
            storage_key=self._storage.storage_key(project_id, media_id),
            size_bytes=staged.size_bytes,
            duration_seconds=metadata.duration,
            video_stream_index=video.index,
            video_codec=video.codec,
            width=video.width,
            height=video.height,
            pixel_format=video.pixel_format,
            frame_rate_numerator=video.frame_rate.numerator,
            frame_rate_denominator=video.frame_rate.denominator,
            audio_stream_index=audio.index if audio else None,
            audio_codec=audio.codec if audio else None,
            audio_sample_rate=audio.sample_rate if audio else None,
            audio_channels=audio.channels if audio else None,
        )

    def _reconcile(self, assets: Sequence[MediaAsset]) -> list[MediaAsset]:
        expected = {asset.id: asset.storage_key for asset in assets}
        try:
            found = self._database.find_media_assets(list(expected))
        except SQLAlchemyError:
            found = []
        if {asset.id: asset.storage_key for asset in found} == expected:
            by_id = {asset.id: asset for asset in found}
            return [by_id[asset.id] for asset in assets]
        # Even an empty snapshot cannot prove an in-flight COMMIT will not finish.
        logger.error(
            "Uncertain commit; retain files and reconcile asset IDs: %s", list(expected)
        )
        raise IngestionError(
            "commit_uncertain",
            "Upload outcome is uncertain. Check the media list before retrying.",
        )
