"""Project request/response contracts and explicit public mapping."""

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from intentcut.backend.storage.database_models import Project


class ProjectCreate(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")
    name: str = Field(min_length=1, max_length=200)


class ProjectResponse(BaseModel):
    id: UUID
    name: str
    # Null only for rows created before the slug migration is applied.
    slug: str | None = None
    created_at: datetime


class ProjectListResponse(BaseModel):
    items: list[ProjectResponse]


def project_response(project: Project) -> ProjectResponse:
    return ProjectResponse(
        id=project.id,
        name=project.name,
        slug=getattr(project, "slug", None),
        created_at=project.created_at,
    )
