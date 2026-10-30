
"use client";

import { RenderVersionPicker } from "./draft-persistence";
import { usePreviewJob } from "./use-editing";
import { draftMatchesSaved, useDraftStore } from "./store/use-draft-store";
import { useAIJobStatus } from "./ai-director/hooks/use-ai-job-status";
import { useAIArtifacts } from "./ai-director/hooks/use-ai-artifacts";
import { VideoArtifactPlayer } from "./ai-director/video-artifact-player";

interface ProgramMonitorProps {
  projectId?: string;
}

function MonitorPlaceholder({
  message,
}: {
  message: string;
}) {
  return (
    <div className="studio-frame">
      <div>
        <svg
          className="studio-monitorIcon"
          viewBox="0 0 48 36"
          fill="none"
          aria-hidden="true"
        >
          <path
            d="M10 1H1v9M38 1h9v9M1 26v9h9m37-9v9h-9"
            stroke="currentColor"
            strokeWidth="1.5"
          />
          <rect
            x="17"
            y="12"
            width="14"
            height="12"
            rx="1"
            stroke="currentColor"
          />
        </svg>

        <h3>Your story takes shape here</h3>
        <p>{message}</p>
      </div>
    </div>
  );
}

function RenderedMonitor({
  projectId,
  jobId,
}: {
  projectId: string;
  jobId: string;
}) {
  const artifacts = useAIArtifacts(projectId, jobId);

  if (artifacts.isPending) {
    return <MonitorPlaceholder message="Loading rendered video metadata..." />;
  }

  if (artifacts.isError) {
    return (
      <div className="space-y-3">
        <p role="alert" className="media-errors">
          Could not load generated artifacts.
        </p>

        <button
          type="button"
          className="button button-secondary"
          onClick={() => void artifacts.refetch()}
        >
          Retry
        </button>
      </div>
    );
  }

  const video = artifacts.data.items.find(
    (artifact) => artifact.kind === "video",
  );

  if (!video) {
    return (
      <MonitorPlaceholder
        message="No video artifact is available for this job."
      />
    );
  }

  return (
    <div className="studio-videoPreview">
      <VideoArtifactPlayer
        key={video.id}
        projectId={projectId}
        jobId={jobId}
        artifactId={video.id}
        sizeBytes={video.size_bytes}
      />
    </div>
  );
}

function JobMonitor({
  projectId,
  jobId,
}: {
  projectId: string;
  jobId: string;
}) {
  const job = useAIJobStatus(projectId, jobId);

  // A refresh failure must not tear down an already confirmed rendered preview.
  if (job.isError && job.data?.status !== "succeeded") {
    return (
      <div className="space-y-3">
        <p role="alert" className="media-errors">
          Unable to retrieve the active job status.
        </p>

        <button
          type="button"
          className="button button-secondary"
          onClick={() => void job.refetch()}
        >
          Retry status check
        </button>
      </div>
    );
  }

  if (job.data?.status === "succeeded") {
    return (
      <RenderedMonitor
        projectId={projectId}
        jobId={jobId}
      />
    );
  }

  if (job.data?.status === "failed") {
    return (
      <MonitorPlaceholder message="The selected render failed. Review job details before retrying." />
    );
  }

  if (job.data?.status === "running") {
    return (
      <MonitorPlaceholder message="The selected video is being processed..." />
    );
  }

  if (job.data?.status === "queued") {
    return (
      <MonitorPlaceholder message="The selected render is queued for processing." />
    );
  }

  return <MonitorPlaceholder message="Loading first cut status..." />;
}

function ConnectedProgramMonitor({
  projectId,
}: {
  projectId: string;
}) {
  const { jobId } = usePreviewJob(projectId);

  if (!jobId) {
    return (
      <MonitorPlaceholder message="Generate your first cut using AI Director." />
    );
  }

  return (
    <JobMonitor
      key={jobId}
      projectId={projectId}
      jobId={jobId}
    />
  );
}

function DraftPreviewNotice({ projectId }: { projectId: string }) {
  const draft = useDraftStore((state) => state.byProject[projectId]);
  const saved = useDraftStore((state) => state.savedByProject[projectId]);
  const {manual} = usePreviewJob(projectId);
  const matches = draft && saved && draftMatchesSaved(draft,saved) && manual?.revision === saved.revision && manual.status === "succeeded";
  return <span>{manual ? `Draft revision ${manual.revision} · ${manual.status}` : "Original AI MP4"} · {matches ? "Matches saved draft" : "Current edits may differ from preview"}</span>;
}

export function ProgramMonitor({
  projectId,
}: ProgramMonitorProps) {
  return (
    <section
      className="studio-panel studio-monitor"
      aria-labelledby="monitor-heading"
    >
      <header className="studio-panelHeader">
        <h2 id="monitor-heading" tabIndex={-1}>Program Monitor</h2>
        {projectId ? <RenderVersionPicker projectId={projectId} /> : <span className="technical">First Cut</span>}
      </header>

      <div className="studio-monitorBody">
        {projectId ? (
          <ConnectedProgramMonitor projectId={projectId} />
        ) : (
          <MonitorPlaceholder message="Open a project to begin." />
        )}

        <div className="studio-monitorMeta">
          <span>Program view</span>
          {projectId ? <DraftPreviewNotice projectId={projectId} /> : <span>Published MP4</span>}
        </div>
      </div>
    </section>
  );
}
