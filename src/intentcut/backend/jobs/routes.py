"""Job admission and status HTTP adapters."""

from uuid import UUID

from fastapi import APIRouter, Response

from intentcut.backend.ai_job_service import AIJobService
from intentcut.backend.contracts import PUBLIC_JOB_ERROR_CODES
from intentcut.backend.first_cut.contracts import FirstCutRequest
from intentcut.backend.jobs.schemas import AIJobAcceptedResponse, AIJobResponse


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
            progress=job.progress if job.has_active_lease is True else None,
        )

    return router
