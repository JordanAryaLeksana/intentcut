"""Project request/response contracts and explicit public mapping."""

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from intentcut.backend.database.database_models import Project


class ProjectCreate(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")
    name: str = Field(min_length=1, max_length=200)


class ProjectResponse(BaseModel):
    id: UUID
    name: str
    created_at: datetime


def project_response(project: Project) -> ProjectResponse:
    return ProjectResponse(
        id=project.id, name=project.name, created_at=project.created_at
    )
