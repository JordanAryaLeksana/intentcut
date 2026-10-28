"""Compatibility exports and the original combined job/artifact router factory."""

from fastapi import APIRouter

from intentcut.backend.ai_job_service import AIJobService
from intentcut.backend.artifacts.routes import SnapshotResponse, create_artifact_router
from intentcut.backend.jobs.routes import create_ai_job_router as create_job_routes
from intentcut.backend.shared.http_security import (
    PRIVATE_HEADERS,
    AIJobLocalAccessMiddleware,
)

__all__ = [
    "PRIVATE_HEADERS",
    "AIJobLocalAccessMiddleware",
    "SnapshotResponse",
    "create_ai_job_router",
]


def create_ai_job_router(service: AIJobService) -> APIRouter:
    """Preserve the legacy factory's complete set of job and artifact routes."""
    router = APIRouter()
    router.include_router(create_job_routes(service))
    router.include_router(create_artifact_router(service))
    return router
