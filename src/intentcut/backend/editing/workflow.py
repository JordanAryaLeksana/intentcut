"""Stable ownership for independent editing heads and immutable job snapshots."""

from typing import Literal

from sqlalchemy import func

from intentcut.backend.storage.database_models import AIJob

Workflow = Literal["first_cut", "highlights"]


def job_workflow(workflow: Workflow):
    # Jobs persisted before workflow isolation belong to First Cut unless migrated.
    return (
        func.coalesce(AIJob.request_payload["workflow"].astext, "first_cut") == workflow
    )
