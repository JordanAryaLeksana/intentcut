-- Batch 2: run explicitly in a transaction after backup/review; never auto-run.
-- Widens allowed kinds, preserves existing rows and the unique (job_id,kind) key.
ALTER TABLE ai_job_artifacts ADD COLUMN IF NOT EXISTS content_type VARCHAR(32);
ALTER TABLE ai_job_artifacts ADD COLUMN IF NOT EXISTS parent_artifact_id UUID;
ALTER TABLE ai_job_artifacts ADD COLUMN IF NOT EXISTS parent_sha256 VARCHAR(64);
DO $$ BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_constraint
                   WHERE conrelid = 'ai_job_artifacts'::regclass
                     AND conname = 'artifact_parent_fk') THEN
        ALTER TABLE ai_job_artifacts ADD CONSTRAINT artifact_parent_fk
            FOREIGN KEY (parent_artifact_id) REFERENCES ai_job_artifacts(id) ON DELETE RESTRICT;
    END IF;
END $$;
ALTER TABLE ai_job_artifacts DROP CONSTRAINT IF EXISTS artifact_kind;
ALTER TABLE ai_job_artifacts ADD CONSTRAINT artifact_kind CHECK (kind IN ('video', 'storyboard', 'captions', 'image', 'rendition'));
ALTER TABLE ai_job_artifacts DROP CONSTRAINT IF EXISTS artifact_parent_pair;
ALTER TABLE ai_job_artifacts ADD CONSTRAINT artifact_parent_pair CHECK ((parent_artifact_id IS NULL AND parent_sha256 IS NULL) OR (parent_artifact_id IS NOT NULL AND parent_sha256 IS NOT NULL AND parent_sha256 ~ '^[0-9a-f]{64}$'));
ALTER TABLE ai_job_artifacts DROP CONSTRAINT IF EXISTS artifact_content_type;
ALTER TABLE ai_job_artifacts ADD CONSTRAINT artifact_content_type CHECK (COALESCE((kind IN ('video','storyboard') AND content_type IS NULL AND parent_artifact_id IS NULL) OR (kind = 'captions' AND content_type = 'application/json' AND parent_artifact_id IS NOT NULL) OR (kind = 'image' AND content_type IN ('image/png','image/jpeg')) OR (kind = 'rendition' AND content_type = 'video/mp4' AND parent_artifact_id IS NOT NULL), false));
