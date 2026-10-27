"""Project HTTP adapter. Database queries live in Database, not handlers."""

from fastapi import APIRouter

from intentcut.backend.api_schemas import (
    ProjectCreate,
    ProjectResponse,
    project_response,
)
from intentcut.backend.database import Database


def create_project_router(database: Database) -> APIRouter:
    router = APIRouter(prefix="/projects", tags=["projects"])

    @router.post("", status_code=201, response_model=ProjectResponse)
    def create_project(body: ProjectCreate) -> ProjectResponse:
        return project_response(database.create_project(body.name))

    return router
