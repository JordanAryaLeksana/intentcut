"""Project HTTP adapter. Database queries live in Database, not handlers."""

from uuid import UUID

from fastapi import APIRouter

from intentcut.backend.projects.schemas import (
    ProjectCreate,
    ProjectListResponse,
    ProjectResponse,
    project_response,
)
from intentcut.backend.projects.slug import is_valid_slug
from intentcut.backend.storage.database import Database, ProjectNotFound


def create_project_router(database: Database) -> APIRouter:
    router = APIRouter(prefix="/projects", tags=["projects"])

    @router.post("", status_code=201, response_model=ProjectResponse)
    def create_project(body: ProjectCreate) -> ProjectResponse:
        return project_response(database.create_project(body.name))

    @router.get("", response_model=ProjectListResponse)
    def list_projects() -> ProjectListResponse:
        # Project library: persisted rows only; never creates state.
        return ProjectListResponse(
            items=[project_response(p) for p in database.list_projects()]
        )

    @router.get("/by-slug/{slug}", response_model=ProjectResponse)
    def get_project_by_slug(slug: str) -> ProjectResponse:
        # Readable URLs resolve to the canonical UUID at this boundary;
        # every internal route keeps using the UUID unchanged.
        if not is_valid_slug(slug):
            raise ProjectNotFound
        project = database.get_project_by_slug(slug)
        if project is None:
            raise ProjectNotFound
        return project_response(project)

    @router.get("/{project_id}", response_model=ProjectResponse)
    def get_project(project_id: UUID) -> ProjectResponse:
        # Reopening a project URL must prove the persisted row still
        # exists instead of letting every Studio panel fail separately.
        project = database.get_project(project_id)
        if project is None:
            raise ProjectNotFound
        return project_response(project)

    return router
