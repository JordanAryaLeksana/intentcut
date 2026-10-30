"""Persisted proposals with fake inference; real PostgreSQL and FFmpeg on accept."""

from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from pathlib import Path
from unittest.mock import Mock
from uuid import UUID, uuid4

import pytest
import test_manual_editing
from sqlalchemy import func, text, update

from intentcut.backend.ai_artifacts import AIArtifactPublisher
from intentcut.backend.ai_job_service import AIJobService
from intentcut.backend.ai_worker import AIJobWorker
from intentcut.backend.contracts import ProposalResult
from intentcut.backend.editing.revisions import RevisionProcessor, complete_proposal
from intentcut.backend.editing.service import EditingService
from intentcut.backend.storage.database_models import AIJob

pytestmark = [pytest.mark.integration, pytest.mark.postgres]
setup = test_manual_editing.setup


def prepare(setup, database, storage):
    api, project, body, manual, published = setup
    saved = api.put(f"/projects/{project}/edit-draft", json=body).json()
    # The real HTTP service has configured fake credentials; processor is isolated.
    muse = Mock()
    processor = RevisionProcessor(EditingService(AIJobService(database, storage)), muse)
    worker = AIJobWorker(
        database, processor, artifact_publisher=AIArtifactPublisher(storage)
    )
    return api, project, body, saved, manual, muse, worker


def proposal(indices):
    return {
        "outcome": "proposed",
        "window_indices": indices,
        "explanation": "Apply the requested sequence change.",
        "reasons": [
            {"window_index": i, "reason": "Retain this cut in the requested order."}
            for i in indices
        ],
    }


def request(api, project, revision=1, instruction="Reverse the existing cuts"):
    body = {
        "request_id": str(uuid4()),
        "draft_revision": revision,
        "instruction": instruction,
    }
    response = api.post(f"/projects/{project}/edit-draft/proposals", json=body)
    assert response.status_code == 202, response.text
    return response.json()["id"], body


def test_proposal_accepts_exact_revision_and_renders_real_mp4(setup, database, storage):
    api, project, body, saved, manual, muse, worker = prepare(setup, database, storage)
    path = f"/projects/{project}/edit-draft"
    indices = list(reversed(saved["window_indices"]))
    muse.revise.return_value = proposal(indices)
    id, submitted = request(api, project)
    assert api.post(path + "/proposals", json=submitted).json()["id"] == id
    assert api.get(path + "/proposals/" + id).json()["job_status"] == "queued"
    assert api.get(path).json()["draft"] == saved
    worker.process_one(job_id=UUID(id))
    result = api.get(path + "/proposals/" + id).json()
    assert result["state"] == "pending" and result["job_status"] == "succeeded"
    assert result["after"] == indices and result["changes"]["reordered"]
    assert api.get(path).json()["draft"] == saved
    accepted = api.post(path + f"/proposals/{id}/accept", json={"expected_revision": 1})
    assert accepted.status_code == 200, accepted.text
    assert accepted.json()["proposal"]["state"] == "accepted"
    assert accepted.json()["draft"]["revision"] == 2
    assert accepted.json()["draft"]["window_indices"] == indices
    assert (
        api.post(
            path + f"/proposals/{id}/accept", json={"expected_revision": 1}
        ).status_code
        == 200
    )
    assert api.get(path + "/proposals").json()["items"][0]["state"] == "accepted"
    render = api.post(path + "/renders", json={"revision": 2}).json()["id"]
    manual.process_one(job_id=UUID(render), manual_only=True)
    assert (
        api.get(f"/projects/{project}/ai-jobs/{render}").json()["status"] == "succeeded"
    )
    assert muse.revise.call_count == 1
    assert muse.analyze.call_count == 0 and muse.select.call_count == 0


def test_removal_rejection_and_cross_project_references(setup, database, storage):
    api, project, body, saved, _, muse, worker = prepare(setup, database, storage)
    path = f"/projects/{project}/edit-draft"
    muse.revise.return_value = proposal(saved["window_indices"][:1])
    id, _ = request(api, project, instruction="Remove the last cut")
    worker.process_one(job_id=UUID(id))
    assert (
        api.get(path + f"/proposals/{id}").json()["changes"]["removed"]
        == saved["window_indices"][1:]
    )
    other = api.post("/projects", json={"name": "Other"}).json()["id"]
    for suffix in ["", "/accept", "/reject"]:
        url = f"/projects/{other}/edit-draft/proposals/{id}{suffix}"
        response = (
            api.get(url) if not suffix else api.post(url, json={"expected_revision": 1})
        )
        assert response.status_code == 404
    assert (
        api.post(path + f"/proposals/{id}/reject").json()["proposal"]["state"]
        == "rejected"
    )
    assert api.get(path).json()["draft"] == saved
    assert (
        api.post(
            path + f"/proposals/{id}/accept", json={"expected_revision": 1}
        ).status_code
        == 409
    )


def test_stale_and_concurrent_accept_never_overwrite_manual_edits(
    setup, database, storage
):
    api, project, body, saved, _, muse, worker = prepare(setup, database, storage)
    path = f"/projects/{project}/edit-draft"
    muse.revise.return_value = proposal(list(reversed(saved["window_indices"])))
    id, _ = request(api, project)
    worker.process_one(job_id=UUID(id))
    manual = api.put(
        path,
        json={
            **body,
            "expected_revision": 1,
            "window_indices": saved["window_indices"][:1],
        },
    ).json()
    assert (
        api.post(
            path + f"/proposals/{id}/accept", json={"expected_revision": 1}
        ).status_code
        == 409
    )
    assert api.get(path + f"/proposals/{id}").json()["state"] == "stale"
    assert api.get(path).json()["draft"] == manual
    # Proposal against revision 2, racing manual save against accept.
    muse.revise.return_value = proposal(saved["window_indices"][:1])
    # Restore two cuts, then produce a valid reordered proposal.
    api.put(path, json={**body, "expected_revision": 2})
    muse.revise.return_value = proposal(list(reversed(saved["window_indices"])))
    id2, _ = request(api, project, revision=3)
    worker.process_one(job_id=UUID(id2))
    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [
            pool.submit(
                api.post,
                path + f"/proposals/{id2}/accept",
                json={"expected_revision": 3},
            ),
            pool.submit(api.put, path, json={**body, "expected_revision": 3}),
        ]
        assert sorted(f.result().status_code for f in futures) == [200, 409]
    assert api.get(path).json()["draft"]["revision"] == 4


@pytest.mark.parametrize(
    "mode,code",
    [
        ("fabricated", "invalid_ai_selection"),
        ("unsupported", "unsupported_revision"),
        ("provider", "provider_unavailable"),
    ],
)
def test_provider_failures_do_not_modify_draft(setup, database, storage, mode, code):
    api, project, _, saved, _, muse, worker = prepare(setup, database, storage)
    if mode == "provider":
        muse.revise.side_effect = RuntimeError("private-provider-secret")
    elif mode == "unsupported":
        muse.revise.return_value = {
            "outcome": "unsupported",
            "window_indices": [],
            "explanation": "Music is unsupported.",
            "reasons": [],
        }
    else:
        muse.revise.return_value = proposal([999])
    id, _ = request(
        api, project, instruction="Add music" if mode == "unsupported" else "Reverse"
    )
    worker.process_one(job_id=UUID(id))
    result = api.get(f"/projects/{project}/edit-draft/proposals/{id}")
    assert result.json()["state"] == "failed" and result.json()["error_code"] == code
    assert "private-provider-secret" not in result.text
    assert api.get(f"/projects/{project}/edit-draft").json()["draft"] == saved


def test_rejection_and_expired_lease_fence_publication(setup, database, storage):
    api, project, _, saved, _, muse, worker = prepare(setup, database, storage)
    path = f"/projects/{project}/edit-draft/proposals"
    id, _ = request(api, project)
    old = database.claim_next_ai_job(job_id=UUID(id))
    with database.engine.begin() as connection:
        connection.execute(
            update(AIJob)
            .where(AIJob.id == UUID(id))
            .values(lease_expires_at=func.clock_timestamp() - timedelta(seconds=1))
        )
    assert not complete_proposal(
        database, old, ProposalResult(proposal(list(reversed(saved["window_indices"]))))
    )
    database.recover_expired_ai_job(job_id=UUID(id), max_attempts=2)
    muse.revise.return_value = proposal(list(reversed(saved["window_indices"])))
    worker.process_one(job_id=UUID(id))
    assert api.get(path + "/" + id).json()["job_status"] == "succeeded"
    id2, _ = request(api, project)
    assert api.post(path + f"/{id2}/reject").status_code == 200
    assert worker.process_one(job_id=UUID(id2)) is False
    assert muse.revise.call_count == 1
    migration = Path("scripts/migrations/003_revision_proposals.sql").read_text()
    with database.engine.begin() as connection:
        connection.execute(text(migration))
        connection.execute(text(migration))
    assert api.get(path + f"/{id2}").json()["state"] == "rejected"


def test_changed_head_before_inference_avoids_provider_call(setup, database, storage):
    api, project, body, saved, _, muse, worker = prepare(setup, database, storage)
    path = f"/projects/{project}/edit-draft"
    id, _ = request(api, project)
    api.put(path, json={**body, "expected_revision": 1})
    worker.process_one(job_id=UUID(id))
    result = api.get(path + f"/proposals/{id}").json()
    assert result["state"] == "stale"
    assert result["error_code"] == "draft_revision_changed"
    muse.revise.assert_not_called()


def test_migration_creation_and_idempotency(database):
    migration = Path("scripts/migrations/003_revision_proposals.sql").read_text()
    with database.engine.begin() as connection:
        connection.execute(text("DROP TABLE revision_proposals"))
        connection.execute(text(migration))
        connection.execute(text(migration))
        assert connection.scalar(text("SELECT count(*) FROM revision_proposals")) == 0
