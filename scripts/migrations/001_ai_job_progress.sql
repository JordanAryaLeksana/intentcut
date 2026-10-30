-- Run explicitly with psql --single-transaction --file; no startup migration.
-- Nullable and additive: existing workers can continue with progress = NULL.
ALTER TABLE ai_jobs ADD COLUMN IF NOT EXISTS progress JSONB;
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'ai_job_progress_object'
          AND conrelid = 'ai_jobs'::regclass
    ) THEN
        ALTER TABLE ai_jobs ADD CONSTRAINT ai_job_progress_object
            CHECK (progress IS NULL OR jsonb_typeof(progress) = 'object');
    END IF;
END $$;
