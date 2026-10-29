"use client";

import { useQuery } from "@tanstack/react-query";
import { savedDraftOptions } from "./use-editing";
import { useEffect, type CSSProperties, type ReactNode } from "react";
import { useDraftStore } from "./store/use-draft-store";
import { DraftTimeline } from "./draft-timeline";
import { useActiveJobId, useEditorStore } from "./store/use-editor-store";
import { useAIJobStatus } from "./ai-director/hooks/use-ai-job-status";
import { useAIArtifacts } from "./ai-director/hooks/use-ai-artifacts";
import { usePublicStoryboard } from "./ai-director/hooks/use-public-storyboard";
import type { PublicStoryboard } from "./ai-director/storyboard/storyboard-schema";

export function TimelineMessage({
  title, children, retry,
}: {
  title: string;
  children: ReactNode;
  retry?: () => void;
}) {
  return (
    <div className="studio-emptyTimeline">
      <div>
        <h3 role={retry ? "alert" : "status"}>{title}</h3>
        <p>{children}</p>
        {retry && <button type="button" className="button button-secondary studio-timelineRetry" onClick={retry}>Retry retrieval</button>}
      </div>
    </div>
  );
}

export function StoryboardCuts({ storyboard }: { storyboard: PublicStoryboard }) {
  return (
    <div className="studio-storyboard" role="region" aria-label="Published storyboard sequence" tabIndex={0}>
      <p className="studio-storyboardSummary" role="status">
        {storyboard.cuts.length} scenes · Planned cuts {storyboard.total_seconds.toFixed(2)}s
      </p>
      <ol
        className="studio-cutList"
        aria-label="Narrative storyboard cuts"
        style={{
          "--cut-tracks": storyboard.cuts.map((cut) => `${cut.end_seconds - cut.start_seconds}fr`).join(" "),
          "--sequence-min-width": `${storyboard.total_seconds * 76}px`,
        } as CSSProperties}
      >
        {storyboard.cuts.map((cut, index) => (
          <li key={cut.window_index} className="studio-cut" title={`Cut ${index + 1} · Source ${cut.start_seconds.toFixed(2)}s – ${cut.end_seconds.toFixed(2)}s`}>
            <div className="studio-cutHeading">
              <h3>Cut {index + 1}</h3>
              <span className="technical">{(cut.end_seconds - cut.start_seconds).toFixed(2)}s</span>
            </div>
            <p>Source: {cut.start_seconds.toFixed(2)}s – {cut.end_seconds.toFixed(2)}s</p>
            {cut.playback_order !== undefined && <p>Playback order: {cut.playback_order}</p>}
            {cut.media_id && <p className="studio-cutMedia">Media: {cut.media_id}</p>}
          </li>
        ))}
      </ol>
      <p className="studio-storyboardNote">Read-only storyboard · Source ranges describe original footage. Exact synchronization with the rendered video is unavailable.</p>
    </div>
  );
}

function LoadedStoryboard({ projectId, jobId, artifactId }: { projectId: string; jobId: string; artifactId: string }) {
  const storyboard = usePublicStoryboard(projectId, jobId, artifactId, true);
  const receive = useDraftStore((state) => state.receive);
  useEffect(() => {
    if (storyboard.data && useEditorStore.getState().activeJobByProject[projectId] === jobId) receive(projectId, { jobId, artifactId }, storyboard.data);
  }, [projectId, jobId, artifactId, storyboard.data, receive]);
  if (storyboard.isError) return <TimelineMessage title="Could not load storyboard" retry={() => void storyboard.refetch()}>Storyboard retrieval or validation failed. Retry to retrieve the existing artifact.</TimelineMessage>;
  if (storyboard.isPending) return <TimelineMessage title="Loading storyboard">Retrieving published cuts…</TimelineMessage>;
  return <StoryboardCuts storyboard={storyboard.data} />;
}

function JobStoryboard({ projectId, jobId }: { projectId: string; jobId: string }) {
  const artifacts = useAIArtifacts(projectId, jobId);
  if (artifacts.isError) return <TimelineMessage title="Could not retrieve artifacts" retry={() => void artifacts.refetch()}>Retry to check the existing job’s artifacts.</TimelineMessage>;
  if (artifacts.isPending) return <TimelineMessage title="Loading storyboard">Checking generated artifacts…</TimelineMessage>;
  const storyboard = artifacts.data.items.find((artifact) => artifact.kind === "storyboard");
  if (!storyboard) return <TimelineMessage title="No storyboard artifact available" retry={() => void artifacts.refetch()}>This job succeeded but returned no storyboard. Check again without generating another cut.</TimelineMessage>;
  return <LoadedStoryboard key={storyboard.id} projectId={projectId} jobId={jobId} artifactId={storyboard.id} />;
}

export function JobTimeline({ projectId, jobId }: { projectId: string; jobId: string }) {
  const job = useAIJobStatus(projectId, jobId);
  // Published cuts remain readable if only the job-status refresh fails.
  if (job.isError && job.data?.status !== "succeeded") return <TimelineMessage title="Could not retrieve job status" retry={() => void job.refetch()}>The saved job may be unavailable or deleted. No new job has been submitted.</TimelineMessage>;
  if (!job.data) return <TimelineMessage title="Loading job status">Checking the selected first cut…</TimelineMessage>;
  switch (job.data.status) {
    case "queued": return <TimelineMessage title="First cut queued">Your storyboard will appear after processing succeeds.</TimelineMessage>;
    case "running": return <TimelineMessage title="First cut processing">Your storyboard is being prepared.</TimelineMessage>;
    case "failed": return <TimelineMessage title="First cut failed">No storyboard is available for this failed job. Review AI Director for details.</TimelineMessage>;
    case "succeeded": return <JobStoryboard projectId={projectId} jobId={jobId} />;
    default: return <TimelineMessage title="Job status unavailable">The selected job returned an unsupported status.</TimelineMessage>;
  }
}

function ConnectedTimeline({ projectId }: { projectId: string }) {
  const jobId = useActiveJobId(projectId);
  const draft = useDraftStore((state) => state.byProject[projectId]);
  const restored = useDraftStore((state) => state.restoredByProject[projectId]);
  const restore = useDraftStore((state) => state.restore);
  const saved = useQuery(savedDraftOptions(projectId));
  useEffect(() => {if (saved.isSuccess) restore(projectId, saved.data);}, [projectId, restore, saved.isSuccess, saved.data]);
  if (!restored) {
    if (saved.isError) return <TimelineMessage title="Could not restore saved draft" retry={() => void saved.refetch()}>Your saved edits have not been replaced. Retry before editing this project.</TimelineMessage>;
    return <TimelineMessage title="Restoring saved draft">Checking persistent project edits…</TimelineMessage>;
  }
  return <>
    {draft && <DraftTimeline projectId={projectId} draft={draft} />}
    <div hidden={Boolean(draft)} style={draft ? undefined : { display: "contents" }}>
      {jobId
        ? <JobTimeline key={jobId} projectId={projectId} jobId={jobId} />
        : <TimelineMessage title="No active first cut">Generate a first cut using AI Director to see its storyboard here.</TimelineMessage>}
    </div>
  </>;
}

export function NarrativeTimeline({ projectId }: { projectId?: string }) {
  return (
    <section className="studio-panel studio-timeline" aria-labelledby="timeline-heading">
      <header className="studio-panelHeader"><h2 id="timeline-heading">Narrative Timeline</h2><span>Working draft · Versioned saves</span></header>
      <div className="studio-timelineBody">
        <div className="studio-trackLabel"><span className="studio-overline">Story sequence</span><span>Draft cuts</span></div>
        {projectId
          ? <ConnectedTimeline key={projectId} projectId={projectId} />
          : <TimelineMessage title="Every story starts with a first scene">Open a project to view its storyboard.</TimelineMessage>}
      </div>
    </section>
  );
}
