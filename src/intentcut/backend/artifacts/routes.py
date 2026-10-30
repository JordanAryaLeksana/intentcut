"""Artifact listing and verified-snapshot HTTP downloads."""

from collections.abc import Iterator
from typing import BinaryIO
from uuid import UUID

from fastapi import APIRouter
from starlette.responses import StreamingResponse
from starlette.types import Receive, Scope, Send

from intentcut.backend.ai_job_service import AIJobService
from intentcut.backend.artifacts.derived import CONTENT_TYPES
from intentcut.backend.artifacts.schemas import (
    AIJobArtifactListResponse,
    AIJobArtifactResponse,
)
from intentcut.backend.shared.http_security import PRIVATE_HEADERS


class SnapshotResponse(StreamingResponse):
    def __init__(
        self,
        snapshot: BinaryIO,
        artifact_id: UUID,
        kind: str,
        content_type: str | None = None,
    ) -> None:
        self.snapshot = snapshot
        snapshot.seek(0, 2)
        size = snapshot.tell()
        snapshot.seek(0)
        if kind not in CONTENT_TYPES:
            snapshot.close()
            raise ValueError("Unsupported artifact kind")
        if content_type is None and kind in {"video", "storyboard"}:
            content_type = "video/mp4" if kind == "video" else "application/json"
        if content_type not in CONTENT_TYPES[kind]:
            snapshot.close()
            raise ValueError("Invalid artifact content type")
        extension = {
            "video/mp4": "mp4",
            "application/json": "json",
            "image/png": "png",
            "image/jpeg": "jpg",
        }[content_type]
        super().__init__(
            self._chunks(),
            media_type=content_type,
            headers={
                **PRIVATE_HEADERS,
                "Content-Length": str(size),
                "Content-Disposition": (
                    f'attachment; filename="{artifact_id}.{extension}"'
                ),
            },
        )

    def _chunks(self) -> Iterator[bytes]:
        while chunk := self.snapshot.read(64 * 1024):
            yield chunk

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        try:
            await super().__call__(scope, receive, send)
        finally:
            self.snapshot.close()


def create_artifact_router(service: AIJobService) -> APIRouter:
    router = APIRouter(prefix="/projects/{project_id}/ai-jobs", tags=["ai-jobs"])

    @router.get(
        "/{job_id}/artifacts",
        response_model=AIJobArtifactListResponse,
        response_model_exclude_none=True,
    )
    def list_artifacts(project_id: UUID, job_id: UUID) -> AIJobArtifactListResponse:
        job = service.get(project_id, job_id)
        lineage = (
            {
                "caption_set_id": job.request_payload["caption_set_id"],
                "caption_revision": job.request_payload["caption_revision"],
            }
            if job.request_payload.get("pipeline_version") == "caption_burn_v1"
            else {}
        )
        return AIJobArtifactListResponse(
            items=[
                AIJobArtifactResponse(
                    **lineage,
                    id=artifact.id,
                    kind=artifact.kind,
                    size_bytes=artifact.size_bytes,
                    content_type=artifact.content_type,
                    parent_artifact_id=artifact.parent_artifact_id,
                    parent_sha256=artifact.parent_sha256,
                    download_url=(
                        f"/projects/{project_id}/ai-jobs/{job_id}/artifacts/{artifact.id}"
                    ),
                )
                for artifact in service.artifacts(project_id, job_id)
            ]
        )

    @router.get(
        "/{job_id}/artifacts/{artifact_id}",
        response_class=StreamingResponse,
        responses={
            200: {
                "content": {
                    "video/mp4": {},
                    "application/json": {},
                    "image/png": {},
                    "image/jpeg": {},
                }
            }
        },
    )
    def download(project_id: UUID, job_id: UUID, artifact_id: UUID) -> SnapshotResponse:
        artifact = service.artifact(project_id, job_id, artifact_id)
        return SnapshotResponse(
            service.snapshot(project_id, artifact),
            artifact.id,
            artifact.kind,
            artifact.content_type,
        )

    return router
