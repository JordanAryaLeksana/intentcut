"""Transcription admission; status and caption downloads use existing routes."""

from datetime import datetime
from uuid import UUID

from fastapi import APIRouter, Response
from pydantic import BaseModel

from intentcut.backend.jobs.domain import AIJobStatus
from intentcut.backend.transcription.service import (
    TranscriptionRequest,
    TranscriptionService,
)


class TranscriptionAccepted(BaseModel):
    id: UUID
    status: AIJobStatus
    created_at: datetime
    status_url: str
    artifacts_url: str


def create_transcription_router(service: TranscriptionService) -> APIRouter:
    router = APIRouter(prefix="/projects/{project_id}/ai-jobs", tags=["transcription"])

    @router.post(
        "/transcriptions", status_code=202, response_model=TranscriptionAccepted
    )
    def submit(
        project_id: UUID, body: TranscriptionRequest, response: Response
    ) -> TranscriptionAccepted:
        job = service.submit(project_id, body)
        url = f"/projects/{project_id}/ai-jobs/{job.id}"
        response.headers["Location"] = url
        return TranscriptionAccepted(
            id=job.id,
            status=job.status,
            created_at=job.created_at,
            status_url=url,
            artifacts_url=f"{url}/artifacts",
        )

    return router
