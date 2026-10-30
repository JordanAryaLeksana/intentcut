"""Validated job-local evidence cache tied to exact source and window bytes."""

import hashlib
import json
import os
from collections.abc import Callable
from contextlib import suppress
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Protocol
from uuid import UUID, uuid4

from intentcut.ai.muse import MODEL, PROMPT
from intentcut.ai.schemas import VideoUnderstandingResult
from intentcut.ai.story_director import GroundedWindow, StorySelection
from intentcut.ai.temporal_windows import TemporalWindow
from intentcut.ai.window_analysis import to_window_evidence
from intentcut.backend.storage.local_media_storage import regular_source


class Muse(Protocol):
    def analyze(self, clip: Path) -> VideoUnderstandingResult: ...

    def select(
        self, evidence: list[dict], intent: str, target_seconds: float
    ) -> StorySelection: ...


def file_digest(path: Path) -> str:
    with regular_source(path) as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


@dataclass(frozen=True)
class PreparedWindow:
    media_id: UUID
    index: int
    window: TemporalWindow
    source_sha256: str
    clip: Path
    sha256: str
    render_seconds: float

    def identity(self) -> dict:
        return {
            "version": "uploaded-window-v1",
            "model": MODEL,
            "prompt_sha256": hashlib.sha256(PROMPT.encode()).hexdigest(),
            "schema_sha256": hashlib.sha256(
                json.dumps(
                    VideoUnderstandingResult.model_json_schema(), sort_keys=True
                ).encode()
            ).hexdigest(),
            "media_id": str(self.media_id),
            "source_sha256": self.source_sha256,
            "source_window_index": self.window.index,
            "start_seconds": self.window.start_seconds,
            "end_seconds": self.window.end_seconds,
            "window_sha256": self.sha256,
        }


class WindowUnderstanding:
    def __init__(self, muse: Muse) -> None:
        self.muse = muse

    @staticmethod
    def cache_path(prepared: PreparedWindow, cache: Path) -> Path:
        key = hashlib.sha256(
            json.dumps(prepared.identity(), sort_keys=True).encode()
        ).hexdigest()
        return cache / f"{key}.json"

    def analyze(
        self,
        prepared: PreparedWindow,
        cache: Path,
        before_inference: Callable[[], None],
    ) -> GroundedWindow:
        identity = prepared.identity()
        path = self.cache_path(prepared, cache)
        if file_digest(prepared.clip) != prepared.sha256:
            raise ValueError("Window fingerprint changed")
        if path.exists() or path.is_symlink():
            with regular_source(path) as stream:
                if os.fstat(stream.fileno()).st_size > 128 * 1024:
                    raise ValueError("Oversized evidence cache")
                cached = json.load(stream)
            if cached.get("identity") != identity:
                raise ValueError("Stale evidence cache")
            result = VideoUnderstandingResult.model_validate(cached["result"])
        else:
            before_inference()
            result = self.muse.analyze(prepared.clip)
            result = VideoUnderstandingResult.model_validate(result.model_dump())
        observations = to_window_evidence(
            str(prepared.media_id), prepared.window, result
        )
        if not path.exists():
            pending = cache / f".{uuid4()}.tmp"
            try:
                with pending.open("x", encoding="utf-8") as stream:
                    json.dump(
                        {"identity": identity, "result": result.model_dump()}, stream
                    )
                    stream.flush()
                    os.fsync(stream.fileno())
                # Another attempt's immutable cache entry may already exist.
                with suppress(FileExistsError):
                    os.link(pending, path)
            finally:
                pending.unlink(missing_ok=True)
        return GroundedWindow(
            media_id=prepared.media_id,
            window_index=prepared.index,
            source_window_index=prepared.window.index,
            start_seconds=prepared.window.start_seconds,
            end_seconds=prepared.window.end_seconds,
            render_seconds=prepared.render_seconds,
            clip=prepared.clip,
            sha256=prepared.sha256,
            summary=result.summary,
            observations=[
                {
                    "description": asdict(item)["description"],
                    "editorial_reason": asdict(item)["editorial_reason"],
                }
                for item in observations
            ],
        )
