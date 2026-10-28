"""Read registered outputs without exposing processor inputs or filesystem paths."""

import hashlib
import json
import os
from tempfile import SpooledTemporaryFile
from typing import BinaryIO
from uuid import UUID

from intentcut.backend.artifacts.schemas import PublicStoryboard
from intentcut.backend.contracts import AIProcessingError
from intentcut.backend.storage.database import Database
from intentcut.backend.storage.database_models import AIJob, AIJobArtifact
from intentcut.backend.first_cut.contracts import FirstCutRequest
from intentcut.backend.first_cut.media_inputs import (
    fingerprint_source,
    plan_inputs,
    processing_available,
)
from intentcut.backend.storage.local_media_storage import LocalMediaStorage
from intentcut.backend.shared.settings import BackendSettings


class AIJobAPIError(Exception):
    def __init__(self, status: int, code: str, message: str) -> None:
        self.status = status
        self.code = code
        self.message = message
        super().__init__(message)


class AIJobService:
    def __init__(
        self,
        database: Database,
        storage: LocalMediaStorage,
        settings: BackendSettings | None = None,
    ) -> None:
        self.database = database
        self.storage = storage
        self.settings = settings

    def create(self, project_id: UUID, body: FirstCutRequest) -> AIJob:
        self.database.require_project(project_id)
        assets = [self.database.get_media(project_id, mid) for mid in body.media_ids]
        if self.settings is None or not processing_available(self.settings):
            raise AIJobAPIError(
                503,
                "upload_inference_unavailable",
                "Uploaded-media processing is not configured in this environment.",
            )
        try:
            plan_inputs(assets, body.target_seconds, self.settings)
            fingerprints = {
                str(asset.id): fingerprint_source(self.storage, asset)
                for asset in assets
            }
        except AIProcessingError as exc:
            raise AIJobAPIError(
                422, exc.code, "Media is unavailable or exceeds processing limits."
            ) from exc
        return self.database.create_ai_job(
            project_id,
            {
                **body.model_dump(mode="json"),
                "pipeline_version": "uploaded_v1",
                "source_sha256": fingerprints,
            },
        )

    def get(self, project_id: UUID, job_id: UUID) -> AIJob:
        job = self.database.get_ai_job(project_id, job_id)
        if job is None:
            raise AIJobAPIError(404, "not_found", "Resource not found.")
        return job

    def artifacts(self, project_id: UUID, job_id: UUID) -> list[AIJobArtifact]:
        self.get(project_id, job_id)
        return self.database.list_ai_job_artifacts(project_id, job_id)

    def artifact(
        self, project_id: UUID, job_id: UUID, artifact_id: UUID
    ) -> AIJobArtifact:
        for artifact in self.artifacts(project_id, job_id):
            if artifact.id == artifact_id:
                return artifact
        raise AIJobAPIError(404, "not_found", "Resource not found.")

    def snapshot(self, project_id: UUID, artifact: AIJobArtifact) -> BinaryIO:
        """Verify a bounded private copy before sending any response bytes.

        The response owns this snapshot. It never reopens the registered pathname;
        replacement or mutation of the original cannot alter an admitted download.
        Large videos spill to a private, automatically removed temporary file.
        """
        # Ownership transfers to SnapshotResponse; errors close it here.
        snapshot = SpooledTemporaryFile(  # noqa: SIM115
            max_size=1024 * 1024, mode="w+b"
        )
        try:
            limit = self.storage.max_file_bytes
            if artifact.kind == "storyboard":
                limit = min(limit, 8 * 1024 * 1024)
            if artifact.kind not in {"video", "storyboard"} or not (
                0 < artifact.size_bytes <= limit
            ):
                raise ValueError("Invalid artifact metadata")
            digest = hashlib.sha256()
            size = 0
            with self.storage.open_object(
                artifact.storage_key, project_id, artifact.id
            ) as source:
                if os.fstat(source.fileno()).st_size != artifact.size_bytes:
                    raise ValueError("Invalid artifact size")
                while chunk := source.read(
                    min(self.storage.chunk_bytes, artifact.size_bytes - size + 1)
                ):
                    size += len(chunk)
                    if size > artifact.size_bytes:
                        raise ValueError("Artifact grew")
                    digest.update(chunk)
                    snapshot.write(chunk)
            if size != artifact.size_bytes or digest.hexdigest() != artifact.sha256:
                raise ValueError("Invalid artifact checksum")
            snapshot.seek(0)
            if artifact.kind == "storyboard":
                public = PublicStoryboard.model_validate(json.load(snapshot))
                snapshot.seek(0)
                snapshot.truncate()
                snapshot.write(
                    public.model_dump_json(exclude_none=True).encode("utf-8")
                )
            elif snapshot.read(8)[4:8] != b"ftyp":
                raise ValueError("Invalid MP4 header")
            snapshot.seek(0)
            return snapshot
        except (OSError, ValueError, RecursionError) as exc:
            snapshot.close()
            raise AIJobAPIError(
                503, "artifact_unavailable", "The artifact is currently unavailable."
            ) from exc
        except BaseException:
            snapshot.close()
            raise
