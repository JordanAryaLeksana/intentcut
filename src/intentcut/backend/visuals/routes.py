from uuid import UUID

from fastapi import APIRouter

from intentcut.backend.visuals.contracts import CoverRequest, RenameImageRequest, VisualRequest
from intentcut.backend.visuals.service import VisualService


def create_visual_router(service: VisualService):
    router = APIRouter(
        prefix="/projects/{project_id}/ai-jobs/visuals", tags=["visuals"]
    )

    @router.post("", status_code=202)
    def submit(project_id: UUID, body: VisualRequest):
        job = service.submit(project_id, body)
        return {
            "id": job.id,
            "status": job.status,
            "status_url": f"/projects/{project_id}/ai-jobs/{job.id}",
        }

    @router.get("")
    def history(project_id: UUID):
        return service.history(project_id)

    @router.put("/cover")
    def cover(project_id: UUID, body: CoverRequest):
        return service.set_cover(project_id, body)
    
    @router.patch("/{job_id}/name")
    def rename_image(
        project_id: UUID,
        job_id: UUID,
        body: RenameImageRequest,
    ):
        return service.rename(project_id, job_id, body.name)
    return router
