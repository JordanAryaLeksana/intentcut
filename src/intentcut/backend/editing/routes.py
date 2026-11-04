"""Manual edit admission uses the same local access boundary as AI jobs."""

from uuid import UUID

from fastapi import APIRouter

from intentcut.backend.editing.service import EditingService, RenderDraft, SaveDraft
from intentcut.backend.editing.workflow import Workflow


def create_editing_router(service: EditingService) -> APIRouter:
    router = APIRouter(prefix="/projects/{project_id}/edit-draft", tags=["editing"])

    @router.get("")
    def get_draft(project_id: UUID, workflow: Workflow = "first_cut"):
        return {"draft": service.get(project_id, workflow)}

    @router.put("")
    def save_draft(project_id: UUID, body: SaveDraft, workflow: Workflow = "first_cut"):
        return service.save(project_id, body, workflow)

    @router.get("/renders")
    def renders(project_id: UUID, workflow: Workflow = "first_cut"):
        return {"items": service.renders(project_id, workflow)}

    @router.post("/renders", status_code=202)
    def render(project_id: UUID, body: RenderDraft, workflow: Workflow = "first_cut"):
        job = service.render(project_id, body, workflow)
        return {
            "id": job.id,
            "status": job.status,
            "status_url": f"/projects/{project_id}/ai-jobs/{job.id}",
        }

    return router
