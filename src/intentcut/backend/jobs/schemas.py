"""Public job acceptance and status contracts; exclude private lease fields."""

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel

from intentcut.backend.jobs.domain import AIJobStatus
from intentcut.backend.jobs.progress import AIJobProgress


class AIJobResponse(BaseModel):
    id: UUID
    status: AIJobStatus
    created_at: datetime
    updated_at: datetime
    started_at: datetime | None
    finished_at: datetime | None
    attempt_count: int
    error_code: str | None
    progress: AIJobProgress | None = None


class AIJobAcceptedResponse(BaseModel):
    id: UUID
    status: Literal["queued"]
    status_url: str
