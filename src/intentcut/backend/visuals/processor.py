"""Muse Image worker; published files remain immutable and retries never repay."""

import hashlib
import os
import re
from contextlib import nullcontext
from uuid import UUID, uuid4

from intentcut.ai.image import MuseImageClient
from intentcut.backend.ai_job_service import AIJobService
from intentcut.backend.artifacts.derived import (
    IMAGE_LIMIT,
    ArtifactParent,
    ImageArtifactResult,
    validate_image,
)
from intentcut.backend.contracts import AIProcessingError, JobLeaseLost
from intentcut.backend.storage.database_models import AIJob
from intentcut.backend.storage.local_media_storage import regular_source
from intentcut.backend.visuals.contracts import PIPELINE
from intentcut.backend.visuals.repository import mutate_payload, reserve_call
from intentcut.backend.visuals.service import image_available
from intentcut.backend.visuals.source import authorized_source
from intentcut.media.process_runner import ProcessRunner


class VisualProcessor:
    def __init__(self, jobs: AIJobService, provider: MuseImageClient):
        self.jobs, self.provider = jobs, provider

    def __call__(self, job: AIJob) -> ImageArtifactResult:
        payload = job.request_payload
        if payload.get("pipeline_version") != PIPELINE:
            raise AIProcessingError("unsupported_job_type")

        def progress(stage):
            if not self.jobs.database.update_ai_job_progress(
                job.project_id, job.id, job.lease_token, stage
            ):
                raise JobLeaseLost("Visual progress fenced")

        if not image_available(self.jobs.settings):
            raise AIProcessingError("processing_failed")
        progress("preparing_media")
        parent_id = payload.get("parent_artifact_id")
        context = (
            authorized_source(
                self.jobs, job.project_id, UUID(parent_id), payload.get("frame_seconds")
            )
            if parent_id
            else nullcontext((None, None, None))
        )
        with context as (parent, source, content_type):
            if parent and parent.sha256 != payload["parent_sha256"]:
                raise AIProcessingError("source_unavailable")
            reference = ArtifactParent(parent.id, parent.sha256) if parent else None
            cache = self.jobs.storage.job_cache(job.id)
            cached = payload.get("image_cache")
            if cached is not None:
                if not isinstance(cached, dict) or not re.fullmatch(
                    r"[0-9a-f]{32}\.png", cached.get("name", "")
                ):
                    raise AIProcessingError("invalid_image_output")
                target = cache / cached["name"]
                with regular_source(target) as stream:
                    if not 0 < os.fstat(stream.fileno()).st_size <= IMAGE_LIMIT:
                        raise AIProcessingError("invalid_image_output")
                    if hashlib.file_digest(stream, "sha256").hexdigest() != cached.get(
                        "sha256"
                    ):
                        raise AIProcessingError("source_unavailable")
                validate_image(target, ProcessRunner())
                return ImageArtifactResult(target, reference)
            if payload.get("image_call_started") is True:
                raise AIProcessingError("image_outcome_unknown")
            workspace = self.jobs.storage.job_workspace(
                job.id, job.attempt_count, job.lease_token
            )
            progress("generating_image")
            reserve_call(self.jobs.database, job)
            data = self.provider.generate(
                payload["prompt"], payload["preset"], job.id, source, content_type
            )
            progress("validating_image")
            if not isinstance(data, bytes) or not 0 < len(data) <= IMAGE_LIMIT:
                raise AIProcessingError("invalid_image_output")
            staged = workspace / "generated.png"
            staged.write_bytes(data)
            if validate_image(staged, ProcessRunner()) != "image/png":
                raise AIProcessingError("invalid_image_output")
            # Cache uses an immutable random filename; a stale worker cannot replace
            # a winner's bytes. Only its fenced DB pointer makes it authoritative.
            name = uuid4().hex + ".png"
            target = cache / name
            with target.open("xb") as destination:
                destination.write(data)
                destination.flush()

                os.fsync(destination.fileno())
            descriptor = os.open(cache, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
            try:
                os.fsync(descriptor)
            finally:
                os.close(descriptor)
            digest = hashlib.sha256(data).hexdigest()

            def save(value):
                if value.get("image_call_started") is not True:
                    raise AIProcessingError("processing_failed")
                value["image_cache"] = {"name": name, "sha256": digest}

            mutate_payload(self.jobs.database, job, save)
            return ImageArtifactResult(target, reference)
