-- Explicit, additive and transactional. AI job snapshots retain base revision/context.
CREATE TABLE IF NOT EXISTS revision_proposals (
    job_id UUID PRIMARY KEY REFERENCES ai_jobs(id) ON DELETE RESTRICT,
    state VARCHAR(16) NOT NULL DEFAULT 'pending'
        CONSTRAINT revision_proposal_state CHECK (state IN ('pending','accepted','rejected','stale')),
    result JSONB CONSTRAINT revision_proposal_result CHECK (result IS NULL OR jsonb_typeof(result) = 'object'),
    applied_revision INTEGER
);
