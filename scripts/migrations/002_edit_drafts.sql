-- Explicit, transactional, additive migration; existing jobs/artifacts are unchanged.
CREATE TABLE IF NOT EXISTS edit_drafts (
    project_id UUID PRIMARY KEY REFERENCES projects(id) ON DELETE RESTRICT,
    base_job_id UUID NOT NULL REFERENCES ai_jobs(id) ON DELETE RESTRICT,
    base_artifact_id UUID NOT NULL REFERENCES ai_job_artifacts(id) ON DELETE RESTRICT,
    revision INTEGER NOT NULL CONSTRAINT edit_draft_revision CHECK (revision > 0),
    window_indices JSONB NOT NULL CONSTRAINT edit_draft_cuts CHECK (jsonb_typeof(window_indices) = 'array'),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
-- Deduplicate render admission for a saved revision, including lost HTTP responses.
CREATE UNIQUE INDEX IF NOT EXISTS uq_manual_render_revision ON ai_jobs
    (project_id, (request_payload->>'draft_revision'))
    WHERE request_payload->>'pipeline_version' = 'manual_v1';
