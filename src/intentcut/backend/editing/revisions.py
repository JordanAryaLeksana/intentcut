"""Persistent revision proposals and atomic, lease-fenced human approval."""

from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import func, select, update

from intentcut.ai.revision import RevisionSelection, validate_revision
from intentcut.backend.ai_job_service import AIJobAPIError
from intentcut.backend.contracts import AIProcessingError, JobLeaseLost, ProposalResult
from intentcut.backend.editing.service import EditingService, conflict
from intentcut.backend.storage.database_models import (
    AIJob,
    EditDraft,
    Project,
    RevisionProposal,
)


class RevisionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    request_id: UUID
    draft_revision: int = Field(gt=0, strict=True)
    instruction: str = Field(min_length=1, max_length=1000)


class AcceptRevision(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expected_revision: int = Field(gt=0, strict=True)


class RevisionService:
    def __init__(self, editing: EditingService):
        self.editing, self.database = editing, editing.database

    def request(self, project_id: UUID, body: RevisionRequest):
        if not body.instruction.strip():
            raise AIJobAPIError(422, "invalid_request", "Describe the sequence change.")
        settings = self.editing.jobs.settings
        if (
            settings is None
            or not settings.ai_processing_enabled
            or not settings.model_api_key
            or not settings.model_api_key.get_secret_value().strip()
        ):
            raise AIJobAPIError(
                503, "revision_unavailable", "AI revisions are not configured."
            )
        saved = self.editing.get(project_id)
        if not saved or saved["revision"] != body.draft_revision:
            raise conflict()
        _, cuts, _ = self.editing.resolve(
            project_id,
            saved["base_job_id"],
            saved["base_artifact_id"],
            saved["window_indices"],
        )
        if not cuts:
            raise AIJobAPIError(
                422,
                "empty_draft",
                "Save a nonempty sequence before requesting a revision.",
            )
        payload = {
            "pipeline_version": "revision_v1",
            "base_revision": body.draft_revision,
            "base_job_id": str(saved["base_job_id"]),
            "base_artifact_id": str(saved["base_artifact_id"]),
            "instruction": body.instruction.strip(),
            "context": {
                "current_sequence": saved["window_indices"],
                "cuts": [c.model_dump(mode="json", exclude_none=True) for c in cuts],
                "context_note": (
                    "Only source references and ranges are available; "
                    "visual descriptions are not public."
                ),
            },
        }
        with self.database._sessions.begin() as session:
            session.scalar(
                select(Project).where(Project.id == project_id).with_for_update()
            )
            existing = session.get(AIJob, body.request_id)
            if existing is not None:
                if existing.project_id != project_id:
                    raise AIJobAPIError(404, "not_found", "Resource not found.")
                if existing.request_payload != payload:
                    raise AIJobAPIError(
                        409, "request_conflict", "Request identifier was already used."
                    )
                return body.request_id
            active = session.scalar(
                select(AIJob.id)
                .where(
                    AIJob.project_id == project_id,
                    AIJob.request_payload["pipeline_version"].astext == "revision_v1",
                    AIJob.status.in_(["queued", "running"]),
                )
                .limit(1)
            )
            if active is not None:
                raise AIJobAPIError(
                    409, "revision_pending", "A revision request is already processing."
                )
            head = session.get(EditDraft, project_id)
            if head is None or head.revision != body.draft_revision:
                raise conflict()
            job = AIJob(
                id=body.request_id,
                project_id=project_id,
                status="queued",
                request_payload=payload,
            )
            session.add(job)
            session.flush()
            session.add(RevisionProposal(job_id=job.id, state="pending"))
        return body.request_id

    def read(self, project_id: UUID, proposal_id: UUID):
        job = self.editing.jobs.get(project_id, proposal_id)
        if job.request_payload.get("pipeline_version") != "revision_v1":
            raise AIJobAPIError(404, "not_found", "Resource not found.")
        with self.database._sessions() as session:
            proposal = session.get(RevisionProposal, proposal_id)
            head = session.get(EditDraft, project_id)
        if proposal is None:
            raise AIJobAPIError(404, "not_found", "Resource not found.")
        payload = job.request_payload
        state = proposal.state
        if state == "pending" and head and head.revision != payload["base_revision"]:
            state = "stale"
        if state == "pending" and job.status == "failed":
            state = "stale" if job.error_code == "draft_revision_changed" else "failed"
        result = proposal.result
        before = payload["context"]["current_sequence"]
        after = result["window_indices"] if result else None
        remaining = [i for i in before if after is not None and i in after]
        return {
            "id": str(job.id),
            "draft_id": str(project_id),
            "base_revision": payload["base_revision"],
            "base_job_id": payload["base_job_id"],
            "base_artifact_id": payload["base_artifact_id"],
            "instruction": payload["instruction"],
            "state": state,
            "job_status": job.status,
            "error_code": job.error_code
            if job.error_code
            in {
                "provider_unavailable",
                "invalid_ai_selection",
                "unsupported_revision",
                "draft_revision_changed",
                "worker_lease_expired",
                "processing_failed",
                "revision_rejected",
            }
            else None,
            "created_at": job.created_at,
            "finished_at": job.finished_at,
            "progress": job.progress if job.has_active_lease is True else None,
            "before": before,
            "after": after,
            "explanation": result["explanation"] if result else None,
            "reasons": result["reasons"] if result else [],
            "changes": {
                "removed": [i for i in before if after is not None and i not in after],
                "reordered": after is not None and remaining != after,
            },
            "applied_revision": proposal.applied_revision,
        }

    def list(self, project_id: UUID):
        self.database.require_project(project_id)
        with self.database._sessions() as session:
            ids = session.scalars(
                select(AIJob.id)
                .where(
                    AIJob.project_id == project_id,
                    AIJob.request_payload["pipeline_version"].astext == "revision_v1",
                )
                .order_by(AIJob.created_at.desc(), AIJob.id.desc())
                .limit(50)
            ).all()
        return {"items": [self.read(project_id, i) for i in ids]}

    def decide(
        self, project_id: UUID, proposal_id: UUID, expected_revision: int | None
    ):
        self.editing.jobs.get(project_id, proposal_id)
        stale = False
        with self.database._sessions.begin() as session:
            session.scalar(
                select(Project).where(Project.id == project_id).with_for_update()
            )
            job = session.scalar(
                select(AIJob)
                .where(AIJob.id == proposal_id, AIJob.project_id == project_id)
                .with_for_update()
            )
            proposal = session.get(RevisionProposal, proposal_id)
            if (
                proposal is None
                or job.request_payload.get("pipeline_version") != "revision_v1"
            ):
                raise AIJobAPIError(404, "not_found", "Resource not found.")
            if expected_revision is None:
                if proposal.state == "accepted":
                    raise conflict()
                proposal.state = "rejected"
                if job.status in {"queued", "running"}:
                    job.status, job.error_code, job.progress = (
                        "failed",
                        "revision_rejected",
                        None,
                    )
                    job.lease_token = job.lease_expires_at = None
                    job.finished_at = session.scalar(select(func.clock_timestamp()))
            else:
                head = session.get(EditDraft, project_id)
                if (
                    proposal.state == "accepted"
                    and head
                    and head.revision == proposal.applied_revision
                ):
                    pass  # Lost acknowledgement: idempotent acceptance.
                elif (
                    proposal.state != "pending"
                    or job.status != "succeeded"
                    or not proposal.result
                ):
                    raise conflict()
                elif (
                    head is None
                    or head.revision != job.request_payload["base_revision"]
                ):
                    proposal.state, stale = "stale", True
                elif expected_revision != head.revision:
                    raise conflict()
                else:
                    validated = validate_revision(
                        RevisionSelection.model_validate(proposal.result),
                        head.window_indices,
                    )
                    head.window_indices = validated.window_indices
                    head.revision += 1
                    head.updated_at = session.scalar(select(func.clock_timestamp()))
                    proposal.state, proposal.applied_revision = (
                        "accepted",
                        head.revision,
                    )
        if stale:
            raise conflict()
        response = self.read(project_id, proposal_id)
        saved = self.editing.get(project_id) if expected_revision is not None else None
        if saved is not None and saved["revision"] != response["applied_revision"]:
            raise conflict()
        return {"proposal": response, "draft": saved}


class RevisionProcessor:
    def __init__(self, editing: EditingService, muse):
        self.editing, self.database, self.muse = editing, editing.database, muse

    def __call__(self, job):
        payload = job.request_payload
        saved = self.editing.get(job.project_id)
        if not saved or saved["revision"] != payload["base_revision"]:
            raise AIProcessingError("draft_revision_changed")
        if not self.database.update_ai_job_progress(
            job.project_id, job.id, job.lease_token, "revising_sequence"
        ):
            raise JobLeaseLost("Revision ownership lost")
        try:
            result = validate_revision(
                RevisionSelection.model_validate(
                    self.muse.revise(payload["context"], payload["instruction"])
                ),
                payload["context"]["current_sequence"],
            )
        except (ValueError, KeyError, TypeError) as exc:
            raise AIProcessingError("invalid_ai_selection") from exc
        except Exception as exc:
            raise AIProcessingError("provider_unavailable") from exc
        if result.outcome == "unsupported":
            raise AIProcessingError("unsupported_revision")
        return ProposalResult(result.model_dump(mode="json"))


def complete_proposal(database, job, result: ProposalResult) -> bool:
    # Result and terminal transition commit together; no inference transaction.
    with database._sessions() as session:
        current = session.scalar(
            select(AIJob)
            .where(AIJob.id == job.id, AIJob.project_id == job.project_id)
            .with_for_update()
        )
        now = session.scalar(select(func.clock_timestamp()))
        if (
            current is None
            or current.status != "running"
            or current.lease_token != job.lease_token
            or current.lease_expires_at is None
            or current.lease_expires_at <= now
        ):
            return False
        proposal = session.get(RevisionProposal, job.id)
        if proposal is None or proposal.state != "pending":
            return False
        checked = validate_revision(
            RevisionSelection.model_validate(result.proposal),
            current.request_payload["context"]["current_sequence"],
        )
        if checked.outcome != "proposed":
            raise ValueError("Unsupported result cannot become a proposal")
        proposal.result = checked.model_dump(mode="json")
        session.flush()
        updated = session.scalar(
            update(AIJob)
            .where(
                AIJob.id == job.id,
                AIJob.status == "running",
                AIJob.lease_token == job.lease_token,
                AIJob.lease_expires_at > func.clock_timestamp(),
            )
            .values(
                status="succeeded",
                progress=None,
                error_code=None,
                lease_token=None,
                lease_expires_at=None,
                finished_at=func.clock_timestamp(),
                updated_at=func.clock_timestamp(),
            )
            .returning(AIJob.id)
        )
        if updated is None:
            return False
        session.commit()
        return True
