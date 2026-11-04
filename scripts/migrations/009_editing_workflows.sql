-- Run once before starting the workflow-aware API and worker. Existing immutable
-- artifacts remain untouched; classify old heads/jobs by their actual base job.
BEGIN;
ALTER TABLE edit_drafts ADD COLUMN workflow varchar(16) NOT NULL DEFAULT 'first_cut';
UPDATE edit_drafts d SET workflow = 'highlights'
FROM ai_jobs j WHERE j.id = d.base_job_id AND j.request_payload->>'pipeline_version' = 'highlight_v1';
ALTER TABLE edit_drafts DROP CONSTRAINT edit_drafts_pkey;
ALTER TABLE edit_drafts ADD PRIMARY KEY (project_id, workflow);
ALTER TABLE edit_drafts ADD CONSTRAINT edit_draft_workflow CHECK (workflow IN ('first_cut', 'highlights'));
UPDATE ai_jobs j SET request_payload = j.request_payload || jsonb_build_object('workflow',
    CASE WHEN b.request_payload->>'pipeline_version' = 'highlight_v1' THEN 'highlights' ELSE 'first_cut' END)
FROM ai_jobs b WHERE j.request_payload->>'pipeline_version' IN ('manual_v1', 'revision_v1')
AND j.request_payload->>'base_job_id' = b.id::text;
DROP INDEX uq_manual_render_revision;
CREATE UNIQUE INDEX uq_manual_render_revision ON ai_jobs
(project_id, (COALESCE(request_payload->>'workflow', 'first_cut')), (request_payload->>'draft_revision'))
WHERE request_payload->>'pipeline_version' = 'manual_v1';
COMMIT;
