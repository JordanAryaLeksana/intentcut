"""Local-only HTTP boundary; project scoping is not per-user authorization."""

import ipaddress
import re
from collections.abc import Iterator
from typing import BinaryIO
from uuid import UUID

from fastapi import APIRouter, Response
from starlette.datastructures import Headers, MutableHeaders
from starlette.responses import JSONResponse, StreamingResponse
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from intentcut.backend.ai_job_service import AIJobService
from intentcut.backend.ai_jobs import PUBLIC_JOB_ERROR_CODES
from intentcut.backend.api_schemas import (
    AIJobAcceptedResponse,
    AIJobArtifactListResponse,
    AIJobArtifactResponse,
    AIJobResponse,
    ErrorResponse,
    FirstCutRequest,
)

PRIVATE_HEADERS = {
    "Cache-Control": "private, no-store",
    "X-Content-Type-Options": "nosniff",
}


class AIJobLocalAccessMiddleware:
    """Opt-in, direct loopback clients only; never trust forwarded identity.

    This is a local development boundary, not an authentication implementation.
    Run on loopback with proxy headers disabled and never behind a public proxy.
    """

    def __init__(self, app: ASGIApp, enabled: bool) -> None:
        self.app = app
        self.enabled = enabled

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or not re.match(
            r"^/projects/[^/]+/ai-jobs(?:/|$)", scope["path"]
        ):
            await self.app(scope, receive, send)
            return

        async def private_send(message: Message) -> None:
            if message["type"] == "http.response.start":
                MutableHeaders(scope=message).update(PRIVATE_HEADERS)
            await send(message)

        if not self.enabled:
            status, code, message = (
                503,
                "ai_api_unavailable",
                "The local AI job API is disabled.",
            )
        elif not self._local_request(scope):
            status, code, message = (
                403,
                "local_access_required",
                "Direct trusted local access is required.",
            )
        else:
            await self.app(scope, receive, private_send)
            return
        response = JSONResponse(
            ErrorResponse(code=code, message=message).model_dump(exclude_none=True),
            status_code=status,
        )
        await response(scope, receive, private_send)

    @staticmethod
    def _local_request(scope: Scope) -> bool:
        client = scope.get("client")
        try:
            if not client or not ipaddress.ip_address(client[0]).is_loopback:
                return False
        except ValueError:
            return False
        headers = Headers(scope=scope)
        hosts = headers.getlist("host")
        # Host checks prevent DNS rebinding. Browser and proxy requests are refused.
        return (
            len(hosts) == 1
            and re.fullmatch(
                r"(?:localhost|127\.0\.0\.1|\[::1\])(?::[0-9]{1,5})?", hosts[0]
            )
            is not None
            and "origin" not in headers
            and headers.get("sec-fetch-site", "none") == "none"
            and not any(
                name in {"forwarded", "via"} or name.startswith("x-forwarded-")
                for name in headers
            )
        )


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


def create_ai_job_router(service: AIJobService) -> APIRouter:
    router = APIRouter(prefix="/projects/{project_id}/ai-jobs", tags=["ai-jobs"])

    @router.post(
        "",
        status_code=202,
        response_model=AIJobAcceptedResponse,
        summary="Queue a first cut from project-owned uploaded media",
    )
    def create_job(
        project_id: UUID, body: FirstCutRequest, response: Response
    ) -> AIJobAcceptedResponse:
        job = service.create(project_id, body)
        status_url = f"/projects/{project_id}/ai-jobs/{job.id}"
        response.headers["Location"] = status_url
        return AIJobAcceptedResponse(id=job.id, status="queued", status_url=status_url)

    @router.get("/{job_id}", response_model=AIJobResponse)
    def get_job(project_id: UUID, job_id: UUID) -> AIJobResponse:
        job = service.get(project_id, job_id)
        # Never serialize the ORM object or its request/lease fields directly.
        code = job.error_code
        if code is not None and code not in PUBLIC_JOB_ERROR_CODES:
            code = "processing_failed"
        return AIJobResponse(
            id=job.id,
            status=job.status,
            created_at=job.created_at,
            updated_at=job.updated_at,
            started_at=job.started_at,
            finished_at=job.finished_at,
            attempt_count=job.attempt_count,
            error_code=code,
        )

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
