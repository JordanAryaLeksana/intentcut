"""Bounded upload admission and immutable source fingerprints, without inference."""

import hashlib
import os
import shutil
from collections.abc import Sequence
from typing import BinaryIO, Literal

from pydantic import Field, model_validator

from intentcut.ai.temporal_windows import TemporalWindow, plan_temporal_window
from intentcut.backend.ai_jobs import AIProcessingError
from intentcut.backend.api_schemas import FirstCutRequest
from intentcut.backend.backend_settings import BackendSettings
from intentcut.backend.database_models import MediaAsset
from intentcut.backend.local_media_storage import LocalMediaStorage


class UploadedFirstCutRequest(FirstCutRequest):
    """Server-only persisted contract; HTTP clients cannot supply fingerprints."""

    pipeline_version: Literal["uploaded_v1"]
    source_sha256: dict[str, str] = Field(min_length=1, max_length=10)

    @model_validator(mode="after")
    def valid_fingerprints(self) -> "UploadedFirstCutRequest":
        if set(self.source_sha256) != {str(media_id) for media_id in self.media_ids}:
            raise ValueError("Source fingerprint membership mismatch")
        for digest in self.source_sha256.values():
            if len(digest) != 64 or any(c not in "0123456789abcdef" for c in digest):
                raise ValueError("Invalid source fingerprint")
        return self


def processing_available(settings: BackendSettings) -> bool:
    return bool(
        settings.ai_processing_enabled
        and settings.model_api_key
        and settings.model_api_key.get_secret_value().strip()
        and shutil.which("ffmpeg")
        and shutil.which("ffprobe")
    )


def plan_inputs(
    assets: Sequence[MediaAsset], target_seconds: float, settings: BackendSettings
) -> list[list[TemporalWindow]]:
    if (
        not 1 <= len(assets) <= settings.ai_max_media
        or len({a.id for a in assets}) != len(assets)
        or sum(a.size_bytes for a in assets) > settings.ai_max_source_bytes
    ):
        raise AIProcessingError("processing_limit")
    plans = []
    try:
        for asset in assets:
            if (
                not 0 < asset.size_bytes <= settings.max_file_bytes
                or max(asset.width, asset.height) > 4096
                or not 0
                < asset.frame_rate_numerator / asset.frame_rate_denominator
                <= 120
            ):
                raise ValueError("Unsupported source limits")
            plans.append(
                plan_temporal_window(
                    asset.duration_seconds,
                    window_seconds=min(5.0, target_seconds),
                    max_windows=settings.ai_max_windows,
                )
            )
        if sum(map(len, plans)) > settings.ai_max_windows:
            raise ValueError("Total window budget exceeded")
        if sum(map(len, plans)) + 1 > settings.ai_max_inference_requests:
            raise ValueError("Inference request budget exceeded")
    except (ValueError, ZeroDivisionError) as exc:
        raise AIProcessingError("processing_limit") from exc
    return plans


def fingerprint_source(
    storage: LocalMediaStorage, asset: MediaAsset, destination: BinaryIO | None = None
) -> str:
    """Read once through no-follow descriptors; optional copy is worker-only."""
    try:
        with storage.open_object(
            asset.storage_key, asset.project_id, asset.id
        ) as source:
            before = os.fstat(source.fileno())
            if not 0 < before.st_size == asset.size_bytes <= storage.max_file_bytes:
                raise ValueError("Source size mismatch")
            digest = hashlib.sha256()
            size = 0
            while chunk := source.read(
                min(storage.chunk_bytes, asset.size_bytes - size + 1)
            ):
                size += len(chunk)
                if size > asset.size_bytes:
                    raise ValueError("Source grew")
                digest.update(chunk)
                if destination is not None:
                    destination.write(chunk)
            after = os.fstat(source.fileno())
            if size != asset.size_bytes or (
                before.st_size,
                before.st_mtime_ns,
                before.st_ctime_ns,
            ) != (after.st_size, after.st_mtime_ns, after.st_ctime_ns):
                raise ValueError("Source changed")
            return digest.hexdigest()
    except (OSError, ValueError) as exc:
        raise AIProcessingError("source_unavailable") from exc
