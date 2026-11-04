
"use client";

import { monitorVideo } from "./monitor-video";
import { useCaptionStore } from "./captions/store";
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
  const selected = useCaptionStore(state=>state.previews[projectId]);

  if (artifacts.isPending) {
    return <MonitorPlaceholder message="Loading your video…" />;
  }

  if (artifacts.isError) {
    return (
      <div className="space-y-3">
        <p role="alert" className="media-errors">
          We couldn’t load your video. Your work is saved — try again.
        </p>

        <button
          type="button"
          className="button button-secondary"
          onClick={() => void artifacts.refetch()}
        >
          Try again
        </button>
      </div>
    );
  }

  const video = monitorVideo(artifacts.data.items, selected?.jobId === jobId ? selected.artifactId : undefined);

  if (!video) {
    return (
      <MonitorPlaceholder
        message="Your video isn’t ready to watch yet."
      />
    );
  }

  return (
    <div className="studio-videoPreview">
      <VideoArtifactPlayer
        key={`${projectId}:${jobId}:${video.id}`}
        autoLoad
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

  // A refresh failure must not tear down an already confirmed preview.
  if (job.isError && job.data?.status !== "succeeded") {
    return (
      <div className="space-y-3">
        <p role="alert" className="media-errors">
          We couldn’t check on your video. It may still be on its way.
        </p>

        <button
          type="button"
          className="button button-secondary"
          onClick={() => void job.refetch()}
        >
          Check again
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
      <MonitorPlaceholder message="This video couldn’t be created. Open AI Director to see what happened." />
    );
  }

  if (job.data?.status === "running") {
    return (
      <MonitorPlaceholder message="Your video is being created…" />
    );
  }

  if (job.data?.status === "queued") {
    return (
      <MonitorPlaceholder message="Your video is waiting to be created…" />
    );
  }

  return <MonitorPlaceholder message="Checking on your video…" />;
}

function ConnectedProgramMonitor({
  projectId,
}: {
  projectId: string;
}) {
  const { jobId: baseJobId, manual, versions } = usePreviewJob(projectId);
  const captioned = useCaptionStore(state=>state.previews[projectId]);
  const jobId = captioned?.jobId ?? baseJobId;

  if (!captioned && versions.isPending) return <MonitorPlaceholder message="Loading video versions…" />;

  if (!jobId) {
    return (
      <MonitorPlaceholder message="Create your first cut with AI Director to watch it here." />
    );
  }

  if (!captioned && manual) {
    if (manual.status === "succeeded") return <RenderedMonitor key={jobId} projectId={projectId} jobId={jobId} />;
    return <MonitorPlaceholder message={manual.status === "queued" ? "Queued · Waiting for worker" : manual.status === "running" ? "Rendering video…" : "This video couldn’t be created. Open Video Activity for details."} />;
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
  const captioned = useCaptionStore(state=>state.previews[projectId]);
  const draft = useDraftStore((state) => state.byProject[projectId]);
  const saved = useDraftStore((state) => state.savedByProject[projectId]);
  const {manual} = usePreviewJob(projectId);
  const matches = draft && saved && draftMatchesSaved(draft,saved) && manual?.revision === saved.revision && manual.status === "succeeded";
  if (captioned) return <span>{captioned.label} · Ready to watch</span>;
  return <span>{manual ? `Version ${manual.revision} · ${manual.status === "succeeded" ? "ready" : manual.status}` : "Your first cut"} · {matches ? "This is your saved draft" : "Your edits aren’t in this preview yet"}</span>;
}

export function ProgramMonitor({
  projectId,
}: ProgramMonitorProps) {
  return (
    <section
      className="studio-panel studio-monitor"
      aria-labelledby="monitor-heading"
      data-tour="export"
    >
      <header className="studio-panelHeader">
        <h2 id="monitor-heading" tabIndex={-1}>Preview &amp; Export</h2>
        {projectId ? <RenderVersionPicker projectId={projectId} /> : <span className="technical">Your first cut</span>}
      </header>

      <div className="studio-monitorBody">
        {projectId ? (
          <ConnectedProgramMonitor projectId={projectId} />
        ) : (
          <MonitorPlaceholder message="Open a project to begin." />
        )}

        <div className="studio-monitorMeta">
          <span>Watch &amp; download</span>
          {projectId ? <DraftPreviewNotice projectId={projectId} /> : <span>Your finished video</span>}
        </div>
      </div>
    </section>
  );
}
