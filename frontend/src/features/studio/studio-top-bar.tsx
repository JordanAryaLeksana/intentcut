"use client";

import Link from "next/link";
import { draftMatchesSaved, useDraftStore } from "./store/use-draft-store";
import { usePreviewJob } from "./use-editing";
import { useAIJobStatus } from "./ai-director/hooks/use-ai-job-status";

export function renderStateLabel(status?: string, error = false): string {
  if (error) return "Job unavailable";
  switch (status) {
    case "queued": return "First cut queued";
    case "running": return "Processing first cut";
    case "succeeded": return "First cut rendered";
    case "failed": return "First cut failed";
    default: return "Checking job";
  }
}

function JobState({ projectId }: { projectId: string }) {
  const {jobId, manual} = usePreviewJob(projectId);
  const job = useAIJobStatus(projectId, jobId);
  return <span className="studio-renderState" role="status">{manual ? `Draft revision ${manual.revision} · ${job.isError ? "Status unavailable" : job.data?.status ?? manual.status}` : jobId ? renderStateLabel(job.data?.status, job.isError) : "No active render"}</span>;
}

function DraftState({ projectId }: { projectId: string }) {
  const draft = useDraftStore((state) => state.byProject[projectId]);
  const saved = useDraftStore((state) => state.savedByProject[projectId]);
  return <span className="studio-draftState">{draft ? draftMatchesSaved(draft,saved) ? `Draft saved · Revision ${saved?.revision}` : "Unsaved draft changes" : "No editing draft"}</span>;
}

export function StudioTopBar({ projectId }: { projectId?: string }) {
  return (
    <header className="studio-topbar">
      <Link href="/" className="studio-brand" aria-label="IntentCut home" translate="no"><span aria-hidden="true">/</span> IntentCut</Link>
      <div className="studio-project">
        <h1 title={projectId}>{projectId ? `Project ${projectId.slice(0, 8)}` : "Studio preview"}</h1>
        <span className="studio-badge">{projectId ? "Local project" : "Session only"}</span>
      </div>
      <div className="studio-toolbarState">
        {projectId ? <JobState key={projectId} projectId={projectId} /> : <span>Open a project to begin</span>}
        {projectId ? <DraftState projectId={projectId} /> : <span className="studio-draftState">Draft saving unavailable</span>}
      </div>
      <nav className="studio-toolbarActions" aria-label="Project actions">
        <Link href="/studio" className="studio-toolbarLink">New project</Link>
        <a href="#monitor-heading" className="button button-secondary">Preview / download</a>
      </nav>
    </header>
  );
}
