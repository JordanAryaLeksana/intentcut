"use client";

import Link from "next/link";
import { WorkflowSwitcher } from "./workflow";
import { useQuery } from "@tanstack/react-query";
import { getProject } from "@/lib/api/projects";
import { TAKE_TOUR_EVENT } from "./studio-tour-logic";
import { DraftSaveStatus } from "./save-draft-control";
import { usePreviewJob } from "./use-editing";
import { useAIJobStatus } from "./ai-director/hooks/use-ai-job-status";

export function renderStateLabel(status?: string, error = false): string {
  if (error) return "We couldn’t check your video";
  switch (status) {
    case "queued": return "Waiting to create your video";
    case "running": return "Creating your video…";
    case "succeeded": return "Your video is ready";
    case "failed": return "Your video couldn’t be created";
    default: return "Checking your video…";
  }
}

function JobState({ projectId }: { projectId: string }) {
  const {jobId, manual} = usePreviewJob(projectId);
  const job = useAIJobStatus(projectId, jobId);
  return <span className="studio-renderState" role="status">{manual ? `Video version ${manual.revision} · ${job.isError ? "We couldn’t check its status" : renderStateLabel(job.data?.status ?? manual.status)}` : jobId ? renderStateLabel(job.data?.status, job.isError) : "No video yet"}</span>;
}

function ProjectTitle({ projectId }: { projectId: string }) {
  const project = useQuery({
    queryKey: ["projects", projectId, "title"] as const,
    queryFn: ({ signal }) => getProject(projectId, signal),
    retry: false,
    staleTime: 60_000,
  });
  return <h1>{project.data?.name ?? "Your project"}</h1>;
}

export function StudioTopBar({ projectId }: { projectId?: string }) {
  return (
    <header className="studio-topbar">
      <Link href="/" className="studio-brand" aria-label="IntentCut home" translate="no"><span aria-hidden="true">/</span> IntentCut</Link>
      <div className="studio-project">
        {projectId ? <ProjectTitle projectId={projectId} /> : <h1>Studio preview</h1>}
        <span className="studio-badge">{projectId ? "Project workspace" : "Preview only"}</span>
      </div>
      {projectId && <WorkflowSwitcher projectId={projectId} />}
      <div className="studio-toolbarState">
        {projectId ? <JobState key={projectId} projectId={projectId} /> : <span>Open a project to begin</span>}
        {projectId ? <DraftSaveStatus projectId={projectId} /> : <span className="studio-draftState">Open a project to save a draft</span>}
      </div>
      <nav className="studio-toolbarActions" aria-label="Project actions">
        <Link href="/studio" className="studio-toolbarLink">All projects</Link>
        <a href="#monitor-heading" className="button button-secondary">Watch & download</a>
        <details className="studio-help">
          <summary>Help</summary>
          <div className="studio-helpPanel">
            <p>New here? Take the short tour — it highlights each part of the Studio and never changes your work.</p>
            <button
              type="button"
              className="button button-primary"
              onClick={(event) => {
                event.currentTarget.closest("details")?.removeAttribute("open");
                window.dispatchEvent(new Event(TAKE_TOUR_EVENT));
              }}
            >
              Take a tour
            </button>
          </div>
        </details>
      </nav>
    </header>
  );
}
