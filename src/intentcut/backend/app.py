"""Application factory: wire dependencies explicitly, without import-time I/O."""

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from sqlalchemy.exc import SQLAlchemyError
from starlette.exceptions import HTTPException
from starlette.responses import JSONResponse

from intentcut.backend.ai_job_service import AIJobAPIError, AIJobService
from intentcut.backend.artifacts.routes import create_artifact_router
from intentcut.backend.storage.database import Database, MediaNotFound, ProjectNotFound
from intentcut.backend.jobs.routes import create_ai_job_router
from intentcut.backend.storage.local_media_storage import LocalMediaStorage
from intentcut.backend.media_ingestion.routes import create_media_router
from intentcut.backend.media_ingestion.service import (
    IngestionError,
    MediaIngestionService,
)
from intentcut.backend.projects.routes import create_project_router
from intentcut.backend.shared.http_errors import ErrorResponse
from intentcut.backend.shared.http_security import (
    PRIVATE_HEADERS,
    AIJobLocalAccessMiddleware,
)
from intentcut.backend.shared.settings import BackendSettings
from intentcut.backend.shared.upload_limits import UploadLimitsMiddleware
from intentcut.media.probe_parser import MediaProbe

logger = logging.getLogger(__name__)


def create_app(
    settings: BackendSettings | None = None,
    *,
    database: Database | None = None,
    storage: LocalMediaStorage | None = None,
    probe: MediaProbe | None = None,
) -> FastAPI:
    """Overrides belong to the caller; only an internally created engine is disposed."""
    settings = settings if settings is not None else BackendSettings()
    owns_database = database is None
    database = (
        database
        if database is not None
        else Database.connect(settings.database_url.get_secret_value())
    )
    storage = (
        storage
        if storage is not None
        else LocalMediaStorage(
            settings.media_root, settings.max_file_bytes, settings.copy_chunk_bytes
        )
    )
    probe = probe if probe is not None else MediaProbe()
    service = MediaIngestionService(database, storage, probe, settings.max_upload_files)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        try:
            storage.initialize()
            yield
        finally:
            if owns_database:
                database.close()

    app = FastAPI(title="IntentCut Media Ingestion", version="0.2.0", lifespan=lifespan)
    app.add_middleware(
        UploadLimitsMiddleware, max_body_bytes=settings.max_request_bytes
    )
    app.add_middleware(
        AIJobLocalAccessMiddleware, enabled=settings.ai_jobs_local_enabled
    )
    app.include_router(create_project_router(database))
    app.include_router(create_media_router(database, service, settings))
    ai_service = AIJobService(database, storage, settings)
    app.include_router(create_ai_job_router(ai_service))
    app.include_router(create_artifact_router(ai_service))

    @app.exception_handler(AIJobAPIError)
    async def ai_job_error(request: Request, exc: AIJobAPIError) -> JSONResponse:
        return error_response(exc.status, exc.code, exc.message)

    @app.exception_handler(IngestionError)
    async def ingestion_error(request: Request, exc: IngestionError) -> JSONResponse:
        status = {
            "upload_limit": 413,
            "probe_unavailable": 503,
            "commit_uncertain": 503,
        }.get(exc.code, 422)
        return error_response(status, exc.code, exc.message, exc.file_index)

    @app.exception_handler(ProjectNotFound)
    @app.exception_handler(MediaNotFound)
    async def not_found(request: Request, exc: Exception) -> JSONResponse:
        return error_response(404, "not_found", "Project or media asset not found.")

    @app.exception_handler(RequestValidationError)
    async def invalid_request(
        request: Request, exc: RequestValidationError
    ) -> JSONResponse:
        # Do not echo arbitrary input values or Pydantic exception contexts.
        return error_response(422, "invalid_request", "Request fields are invalid.")

    @app.exception_handler(HTTPException)
    async def http_error(request: Request, exc: HTTPException) -> JSONResponse:
        messages = {
            400: ("invalid_request", "Malformed request or multipart data."),
            404: ("not_found", "Resource not found."),
            405: ("method_not_allowed", "Method not allowed."),
            413: ("upload_limit", "Request body exceeds the size limit."),
            415: ("unsupported_content_type", "Expected multipart/form-data."),
        }
        code, message = messages.get(
            exc.status_code, ("request_failed", "Request failed.")
        )
        return error_response(exc.status_code, code, message)

    @app.exception_handler(SQLAlchemyError)
    async def database_error(request: Request, exc: SQLAlchemyError) -> JSONResponse:
        logger.error("Database operation failed (%s)", type(exc).__name__)
        return error_response(
            503, "database_unavailable", "Database operation is unavailable."
        )

    @app.exception_handler(Exception)
    async def internal_error(request: Request, exc: Exception) -> JSONResponse:
        logger.error("Backend operation failed (%s)", type(exc).__name__)
        return error_response(
            500, "internal_error", "The operation could not be completed."
        )

    return app


def error_response(
    status: int, code: str, message: str, file_index: int | None = None
) -> JSONResponse:
    body = ErrorResponse(code=code, message=message, file_index=file_index)
    return JSONResponse(
        body.model_dump(exclude_none=True), status_code=status, headers=PRIVATE_HEADERS
    )
