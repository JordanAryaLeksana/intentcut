"""Caption editing stays inside the existing local-only AI API boundary."""

from uuid import UUID

from fastapi import APIRouter

from intentcut.backend.captions.schemas import (
    CaptionSetResponse,
    CreateCaptions,
    ExportCaptions,
    SaveCaptions,
)
from intentcut.backend.captions.service import CaptionService


def create_caption_router(service: CaptionService) -> APIRouter:
    router = APIRouter(prefix="/projects/{project_id}/ai-jobs", tags=["captions"])

    @router.get("/videos/{video_id}/captions")
    def state(project_id: UUID, video_id: UUID):
        return service.video_state(project_id, video_id)

    @router.post("/caption-sets", response_model=CaptionSetResponse)
    def create(project_id: UUID, body: CreateCaptions):
        return service.create(project_id, body)

    @router.get("/caption-sets/{caption_id}", response_model=CaptionSetResponse)
    def get(project_id: UUID, caption_id: UUID):
        return service.get(project_id, caption_id)

    @router.put("/caption-sets/{caption_id}", response_model=CaptionSetResponse)
    def save(project_id: UUID, caption_id: UUID, body: SaveCaptions):
        return service.save(project_id, caption_id, body)

    @router.post("/caption-sets/{caption_id}/exports", status_code=202)
    def export(project_id: UUID, caption_id: UUID, body: ExportCaptions):
        job = service.export(project_id, caption_id, body)
        return {
            "id": job.id,
            "status": job.status,
            "status_url": f"/projects/{project_id}/ai-jobs/{job.id}",
        }

    return router
