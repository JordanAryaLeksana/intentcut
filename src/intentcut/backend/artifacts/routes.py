"""Artifact listing and verified-snapshot HTTP downloads."""

from collections.abc import Iterator
from typing import BinaryIO
from uuid import UUID

from fastapi import APIRouter
from starlette.responses import StreamingResponse
from starlette.types import Receive, Scope, Send

from intentcut.backend.ai_job_service import AIJobService
from intentcut.backend.artifacts.schemas import (
    AIJobArtifactListResponse,
    AIJobArtifactResponse,
)
from intentcut.backend.shared.http_security import PRIVATE_HEADERS


class SnapshotResponse(StreamingResponse):
    def __init__(self, snapshot: BinaryIO, artifact_id: UUID, kind: str) -> None:
        self.snapshot = snapshot
        snapshot.seek(0, 2)
        size = snapshot.tell()
        snapshot.seek(0)
        extension = "mp4" if kind == "video" else "json"
        super().__init__(
            self._chunks(),
            media_type="video/mp4" if kind == "video" else "application/json",
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

    @router.get("/{job_id}/artifacts", response_model=AIJobArtifactListResponse)
    def list_artifacts(project_id: UUID, job_id: UUID) -> AIJobArtifactListResponse:
        return AIJobArtifactListResponse(
            items=[
                AIJobArtifactResponse(
                    id=artifact.id,
                    kind=artifact.kind,
                    size_bytes=artifact.size_bytes,
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
        responses={200: {"content": {"video/mp4": {}, "application/json": {}}}},
    )
    def download(project_id: UUID, job_id: UUID, artifact_id: UUID) -> SnapshotResponse:
        artifact = service.artifact(project_id, job_id, artifact_id)
        return SnapshotResponse(
            service.snapshot(project_id, artifact), artifact.id, artifact.kind
        )

    return router
