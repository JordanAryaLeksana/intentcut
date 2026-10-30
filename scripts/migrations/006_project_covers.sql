-- Standalone Batch 5 migration; requires existing base tables and migration 004.
-- Apply only explicitly in a transaction after operator approval and backup.
CREATE TABLE IF NOT EXISTS project_covers (
    project_id UUID PRIMARY KEY REFERENCES projects(id) ON DELETE RESTRICT,
    artifact_id UUID NOT NULL REFERENCES ai_job_artifacts(id) ON DELETE RESTRICT,
    job_id UUID NOT NULL REFERENCES ai_jobs(id) ON DELETE RESTRICT,
    sha256 VARCHAR(64) NOT NULL CONSTRAINT project_cover_hash CHECK (sha256 ~ '^[0-9a-f]{64}$'),
    revision INTEGER NOT NULL CONSTRAINT project_cover_revision CHECK (revision > 0)
);
