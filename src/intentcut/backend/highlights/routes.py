"""Highlight routes stay inside the existing local-only AI API boundary."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Query, Response
from starlette.background import BackgroundTask
from starlette.responses import FileResponse

from intentcut.backend.highlights.contracts import (
    CandidateListResponse,
    HighlightRequest,
)
from intentcut.backend.highlights.service import HighlightService
from intentcut.backend.jobs.schemas import AIJobAcceptedResponse


def create_highlight_router(service: HighlightService) -> APIRouter:
    router = APIRouter(prefix="/projects/{project_id}/ai-jobs", tags=["highlights"])

    @router.post(
        "/highlights",
        status_code=202,
        response_model=AIJobAcceptedResponse,
        summary="Queue a highlight reel from one long-form source",
    )
    def create_job(
        project_id: UUID, body: HighlightRequest, response: Response
    ) -> AIJobAcceptedResponse:
        job = service.create(project_id, body)
        status_url = f"/projects/{project_id}/ai-jobs/{job.id}"
        response.headers["Location"] = status_url
        return AIJobAcceptedResponse(id=job.id, status="queued", status_url=status_url)

    @router.get("/highlights/candidates", response_model=CandidateListResponse)
    def list_candidates(
        project_id: UUID,
        media_id: Annotated[UUID, Query()],
        candidate_seconds: Annotated[float, Query(gt=0, le=30)] = 8.0,
        max_candidates: Annotated[int, Query(ge=1, le=12)] = 8,
    ):
        return service.candidates(
            project_id,
            media_id,
            candidate_seconds=candidate_seconds,
            max_candidates=max_candidates,
        )

    @router.get(
        "/highlights/preview",
        response_class=FileResponse,
        responses={200: {"content": {"video/mp4": {}}}},
        summary="Extract one bounded candidate clip for Navigator preview",
    )
    def preview_clip(
        project_id: UUID,
        media_id: Annotated[UUID, Query()],
        start_seconds: Annotated[float, Query(ge=0)],
        end_seconds: Annotated[float, Query(gt=0)],
    ):
        clip = service.preview_clip(project_id, media_id, start_seconds, end_seconds)
        return FileResponse(
            clip,
            media_type="video/mp4",
            filename="highlight-preview.mp4",
            background=BackgroundTask(service.discard_preview, clip),
        )

    return router
