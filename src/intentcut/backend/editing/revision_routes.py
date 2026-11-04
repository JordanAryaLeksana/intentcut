from uuid import UUID

from fastapi import APIRouter

from intentcut.backend.editing.revisions import (
    AcceptRevision,
    RevisionRequest,
    RevisionService,
)
from intentcut.backend.editing.workflow import Workflow


def create_revision_router(service: RevisionService):
    router = APIRouter(
        prefix="/projects/{project_id}/edit-draft/proposals", tags=["revisions"]
    )

    @router.post("", status_code=202)
    def request_revision(
        project_id: UUID, body: RevisionRequest, workflow: Workflow = "first_cut"
    ):
        proposal_id = service.request(project_id, body, workflow)
        return {
            "id": proposal_id,
            "status_url": f"/projects/{project_id}/edit-draft/proposals/{proposal_id}",
        }

    @router.get("")
    def list_proposals(project_id: UUID, workflow: Workflow = "first_cut"):
        return service.list(project_id, workflow)

    @router.get("/{proposal_id}")
    def get_proposal(
        project_id: UUID, proposal_id: UUID, workflow: Workflow = "first_cut"
    ):
        return service.read(project_id, proposal_id, workflow)

    @router.post("/{proposal_id}/accept")
    def accept(
        project_id: UUID,
        proposal_id: UUID,
        body: AcceptRevision,
        workflow: Workflow = "first_cut",
    ):
        return service.decide(project_id, proposal_id, body.expected_revision, workflow)

    @router.post("/{proposal_id}/reject")
    def reject(project_id: UUID, proposal_id: UUID, workflow: Workflow = "first_cut"):
        return service.decide(project_id, proposal_id, None, workflow)

    return router
