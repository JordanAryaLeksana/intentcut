"""Manual edit admission uses the same local access boundary as AI jobs."""

from uuid import UUID

from fastapi import APIRouter

from intentcut.backend.editing.service import EditingService, RenderDraft, SaveDraft


def create_editing_router(service: EditingService) -> APIRouter:
    router = APIRouter(prefix="/projects/{project_id}/edit-draft", tags=["editing"])

    @router.get("")
    def get_draft(project_id: UUID):
        return {"draft": service.get(project_id)}

    @router.put("")
    def save_draft(project_id: UUID, body: SaveDraft):
        return service.save(project_id, body)

    @router.get("/renders")
    def renders(project_id: UUID):
        return {"items": service.renders(project_id)}

    @router.post("/renders", status_code=202)
    def render(project_id: UUID, body: RenderDraft):
        job = service.render(project_id, body)
        return {
            "id": job.id,
            "status": job.status,
            "status_url": f"/projects/{project_id}/ai-jobs/{job.id}",
        }

    return router
