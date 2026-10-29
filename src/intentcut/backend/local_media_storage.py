"""Request-owned staging and bounded local copies; no database or HTTP coupling."""

import logging
import os
import shutil
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import BinaryIO
from uuid import UUID, uuid4

logger = logging.getLogger(__name__)


class FileTooLarge(Exception):
    """The byte count exceeded the configured limit."""


class EmptyFile(Exception):
    """An uploaded stream had no bytes."""


@dataclass(frozen=True)
class StagedFile:
    path: Path
    size_bytes: int


class LocalMediaStorage:
    """Store only server-generated paths beneath a trusted, private root."""

    def __init__(self, root: Path, max_file_bytes: int, chunk_bytes: int) -> None:
        if max_file_bytes <= 0 or not 0 < chunk_bytes <= 1024 * 1024:
            raise ValueError(
                "Storage limits must be positive; chunks are at most 1 MiB"
            )
        self.root = root.resolve()
        self.max_file_bytes = max_file_bytes
        self.chunk_bytes = chunk_bytes

    def initialize(self) -> None:
        self.root.mkdir(parents=True, exist_ok=True, mode=0o700)
        self._directory(".staging")
        self._directory("projects")

    def _directory(self, *parts: str) -> Path:
        directory = self.root
        for part in parts:
            directory = directory / part
            if directory.is_symlink():
                raise OSError("Storage directories must not be symlinks")
            directory.mkdir(exist_ok=True, mode=0o700)
        return directory

    @contextmanager
    def staging(self) -> Iterator[Path]:
        """Clean this batch only; a cleanup failure must not undo a confirmed commit."""
        directory = self._directory(".staging") / str(uuid4())
        directory.mkdir(mode=0o700)
        try:
            yield directory
        finally:
            try:
                shutil.rmtree(directory)
            except OSError:
                logger.exception("Staging cleanup failed for batch %s", directory.name)

    def stage(self, stream: BinaryIO, batch: Path, media_id: UUID) -> StagedFile:
        """Read at most one bounded chunk at a time; count bytes independently."""
        path = batch / f"{media_id}.part"
        size = 0
        with path.open("xb") as destination:
            while chunk := stream.read(
                min(self.chunk_bytes, self.max_file_bytes - size + 1)
            ):
                size += len(chunk)
                if size > self.max_file_bytes:
                    raise FileTooLarge
                destination.write(chunk)
        if size == 0:
            raise EmptyFile
        return StagedFile(path, size)

    @staticmethod
    def storage_key(project_id: UUID, media_id: UUID) -> str:
        return f"projects/{project_id}/{media_id}/original"

    def publish(self, staged: Path, project_id: UUID, media_id: UUID) -> Path:
        """Hard-link a complete file; never overwrite or adopt an existing directory."""
        project = self._directory("projects", str(project_id))
        directory = project / str(media_id)
        directory.mkdir(mode=0o700)
        target = directory / "original"
        try:
            os.link(staged, target)
        except OSError:
            directory.rmdir()
            raise
        return target

    def remove_published(self, path: Path) -> None:
        """Remove one request-owned original, leaving the shared project directory."""
        path.unlink(missing_ok=True)
        path.parent.rmdir()
