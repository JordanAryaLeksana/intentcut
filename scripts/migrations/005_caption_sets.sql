-- Apply explicitly in a transaction after migration 004 and approved backup.
CREATE TABLE IF NOT EXISTS caption_sets (
    id UUID PRIMARY KEY REFERENCES ai_job_artifacts(id) ON DELETE RESTRICT,
    project_id UUID NOT NULL REFERENCES projects(id) ON DELETE RESTRICT,
    parent_artifact_id UUID NOT NULL REFERENCES ai_job_artifacts(id) ON DELETE RESTRICT,
    parent_sha256 VARCHAR(64) NOT NULL,
    transcription_sha256 VARCHAR(64) NOT NULL,
    revision INTEGER NOT NULL CONSTRAINT caption_set_revision CHECK (revision > 0),
    duration_ms INTEGER NOT NULL CONSTRAINT caption_set_duration CHECK (duration_ms > 0 AND duration_ms <= 86400000),
    cues JSONB NOT NULL CONSTRAINT caption_set_cues CHECK (jsonb_typeof(cues) = 'array'),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT caption_set_hashes CHECK (parent_sha256 ~ '^[0-9a-f]{64}$' AND transcription_sha256 ~ '^[0-9a-f]{64}$')
);
CREATE INDEX IF NOT EXISTS ix_caption_sets_project_id ON caption_sets(project_id);
CREATE UNIQUE INDEX IF NOT EXISTS uq_caption_export_revision ON ai_jobs
    (project_id, (request_payload->>'caption_set_id'), (request_payload->>'caption_revision'))
    WHERE request_payload->>'pipeline_version' = 'caption_burn_v1';
