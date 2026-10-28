"""Multipart and metadata HTTP adapters, with explicit constructor dependencies."""

from typing import Annotated
from uuid import UUID

import anyio
from fastapi import APIRouter, HTTPException, Query, Request
from starlette.datastructures import UploadFile
from starlette.exceptions import HTTPException as StarletteHTTPException

from intentcut.backend.database.database import Database
from intentcut.backend.media_ingestion.schemas import (
    MediaAssetResponse,
    MediaListResponse,
    MediaUploadResponse,
    media_response,
)
from intentcut.backend.media_ingestion.service import (
    IngestionError,
    MediaIngestionService,
    UploadSource,
)
from intentcut.backend.shared.settings import BackendSettings


def create_media_router(
    database: Database, service: MediaIngestionService, settings: BackendSettings
) -> APIRouter:
    router = APIRouter(prefix="/projects/{project_id}/media", tags=["media"])

    @router.post(
        "",
        status_code=201,
        response_model=MediaUploadResponse,
        openapi_extra={
            "requestBody": {
                "required": True,
                "content": {
                    "multipart/form-data": {
                        "schema": {
                            "type": "object",
                            "required": ["files"],
                            "properties": {
                                "files": {
                                    "type": "array",
                                    "minItems": 1,
                                    "maxItems": settings.max_upload_files,
                                    "items": {"type": "string", "format": "binary"},
                                }
                            },
                        }
                    }
                },
            }
        },
    )
    async def upload_media(project_id: UUID, request: Request) -> MediaUploadResponse:
        content_type = (
            request.headers.get("content-type", "").split(";", 1)[0].strip().lower()
        )
        if content_type != "multipart/form-data":
            raise HTTPException(415, "Expected multipart/form-data.")
        await anyio.to_thread.run_sync(database.require_project, project_id)
        try:
            # Apply file-count limits before all parts have been spooled.
            try:
                form = await request.form(
                    max_files=settings.max_upload_files, max_fields=0
                )
            except StarletteHTTPException as exc:
                if exc.status_code == 400 and str(exc.detail).startswith(
                    "Too many files."
                ):
                    raise IngestionError(
                        "upload_limit", "Too many uploaded files."
                    ) from exc
                raise
            uploads = []
            for key, value in form.multi_items():
                if key != "files" or not isinstance(value, UploadFile):
                    raise IngestionError(
                        "invalid_upload", "Only repeated 'files' parts are accepted."
                    )
                uploads.append(UploadSource(value.filename or "", value.file))
            # Files must stay open until the synchronous worker has finished, even
            # if a client disconnects or the surrounding task receives cancellation.
            with anyio.CancelScope(shield=True):
                assets = await anyio.to_thread.run_sync(
                    service.ingest, project_id, uploads
                )
            return MediaUploadResponse(
                items=[media_response(asset) for asset in assets]
            )
        finally:
            with anyio.CancelScope(shield=True):
                await request.close()

    @router.get("", response_model=MediaListResponse)
    def list_media(
        project_id: UUID,
        limit: Annotated[int, Query(ge=1, le=100)] = 50,
        offset: Annotated[int, Query(ge=0)] = 0,
    ) -> MediaListResponse:
        assets = database.list_media(project_id, limit, offset)
        return MediaListResponse(
            items=[media_response(asset) for asset in assets],
            limit=limit,
            offset=offset,
        )

    @router.get("/{media_id}", response_model=MediaAssetResponse)
    def get_media(project_id: UUID, media_id: UUID) -> MediaAssetResponse:
        return media_response(database.get_media(project_id, media_id))

    return router
