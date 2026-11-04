"use client";

import { useEditingScope } from "./workflow";

import { useQuery } from "@tanstack/react-query";
import { savedDraftOptions } from "./use-editing";
import { useEffect, type CSSProperties, type ReactNode } from "react";
import { useDraftStore } from "./store/use-draft-store";
import { DraftTimeline } from "./draft-timeline";
import { HighlightWorkspace } from "./highlights/highlight-workspace";
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
        {retry && <button type="button" className="button button-secondary studio-timelineRetry" onClick={retry}>Try again</button>}
      </div>
    </div>
  );
}

export function StoryboardCuts({ storyboard }: { storyboard: PublicStoryboard }) {
  return (
    <div className="studio-storyboard" role="region" aria-label="Your story in order" tabIndex={0}>
      <p className="studio-storyboardSummary" role="status">
        {storyboard.cuts.length} moments · {storyboard.total_seconds.toFixed(1)} seconds of story
      </p>
      <ol
        className="studio-cutList"
        aria-label="Your story in order"
        style={{
          "--cut-tracks": storyboard.cuts.map((cut) => `${cut.end_seconds - cut.start_seconds}fr`).join(" "),
          "--sequence-min-width": `${storyboard.total_seconds * 76}px`,
        } as CSSProperties}
      >
        {storyboard.cuts.map((cut, index) => (
          <li key={cut.window_index} className="studio-cut" title={`Moment ${index + 1} · From your footage at ${cut.start_seconds.toFixed(1)}s`}>
            <div className="studio-cutHeading">
              <h3>Moment {index + 1}</h3>
              <span className="technical">{(cut.end_seconds - cut.start_seconds).toFixed(1)}s</span>
            </div>
            <p>From your footage: {cut.start_seconds.toFixed(1)}s – {cut.end_seconds.toFixed(1)}s</p>
            {cut.playback_order !== undefined && <p>Plays {cut.playback_order + 1} in your story</p>}
          </li>
        ))}
      </ol>
      <p className="studio-storyboardNote">This is your story plan. The times show where each moment comes from in your footage.</p>
    </div>
  );
}

function LoadedStoryboard({ projectId, jobId, artifactId }: { projectId: string; jobId: string; artifactId: string }) {
  const { scope } = useEditingScope(projectId);
  const storyboard = usePublicStoryboard(projectId, jobId, artifactId, true);
  const receive = useDraftStore((state) => state.receive);
  useEffect(() => {
    if (storyboard.data && useEditorStore.getState().activeJobByProject[scope] === jobId) receive(scope, { jobId, artifactId }, storyboard.data);
  }, [scope, projectId, jobId, artifactId, storyboard.data, receive]);
  if (storyboard.isError) return <TimelineMessage title="We couldn’t load your story plan" retry={() => void storyboard.refetch()}>Your video is saved. Try again to see the plan — nothing will be created again.</TimelineMessage>;
  if (storyboard.isPending) return <TimelineMessage title="Loading your story">Opening your story plan…</TimelineMessage>;
  return <StoryboardCuts storyboard={storyboard.data} />;
}

function JobStoryboard({ projectId, jobId }: { projectId: string; jobId: string }) {
  const artifacts = useAIArtifacts(projectId, jobId);
  if (artifacts.isError) return <TimelineMessage title="We couldn’t check your video" retry={() => void artifacts.refetch()}>Try again to check what’s already made — nothing new will start.</TimelineMessage>;
  if (artifacts.isPending) return <TimelineMessage title="Loading your story">Checking what’s already made…</TimelineMessage>;
  const storyboard = artifacts.data.items.find((artifact) => artifact.kind === "storyboard");
  if (!storyboard) return <TimelineMessage title="Your story plan is missing" retry={() => void artifacts.refetch()}>Your video finished, but its story plan didn’t come back. Check again — don’t create another cut yet.</TimelineMessage>;
  return <LoadedStoryboard key={storyboard.id} projectId={projectId} jobId={jobId} artifactId={storyboard.id} />;
}

export function JobTimeline({ projectId, jobId }: { projectId: string; jobId: string }) {
  const { workflow } = useEditingScope(projectId);
  const job = useAIJobStatus(projectId, jobId);
  // Your story stays readable if only the progress check fails.
  if (job.isError && job.data?.status !== "succeeded") return <TimelineMessage title="We couldn’t check on your video" retry={() => void job.refetch()}>Your saved work may still be there. Nothing new was started.</TimelineMessage>;
  if (!job.data) return <TimelineMessage title="Loading your video">Checking on your video…</TimelineMessage>;
  switch (job.data.status) {
    case "queued": return <TimelineMessage title="Waiting to create your video">Your story will appear here when it is ready.</TimelineMessage>;
    case "running": return <TimelineMessage title="Creating your video">We are putting your story together…</TimelineMessage>;
    case "failed": return <TimelineMessage title="Your video couldn’t be created">Open {workflow === "highlights" ? "AI Highlights" : "AI First Cut"} to see what happened and try again.</TimelineMessage>;
    case "succeeded": return <JobStoryboard projectId={projectId} jobId={jobId} />;
    default: return <TimelineMessage title="We couldn’t read that update">Your video sent back something we don’t understand. Try checking again.</TimelineMessage>;
  }
}

function ConnectedTimeline({ projectId }: { projectId: string }) {
  const { workflow, scope } = useEditingScope(projectId);
  const jobId = useActiveJobId(projectId);
  const draft = useDraftStore((state) => state.byProject[scope]);
  const restored = useDraftStore((state) => state.restoredByProject[scope]);
  const restore = useDraftStore((state) => state.restore);
  const saved = useQuery(savedDraftOptions(projectId, workflow));
  useEffect(() => {if (saved.isSuccess) restore(scope, saved.data);}, [scope, projectId, restore, saved.isSuccess, saved.data]);
  if (!restored) {
    if (saved.isError) return <TimelineMessage title="We couldn’t reopen your draft" retry={() => void saved.refetch()}>Your saved edits are still saved. Try again before you keep editing.</TimelineMessage>;
    return <TimelineMessage title="Reopening your draft">Bringing back your saved edits…</TimelineMessage>;
  }
  if (workflow === "highlights") return <>
    <HighlightWorkspace key={scope} projectId={projectId} draft={draft} />
    {/* Keep recovery for a newly generated job mounted, even while editing an
        older draft. The existing receive() logic handles pending newer cuts. */}
    {draft && jobId && jobId !== draft.base.jobId && <div hidden><JobTimeline key={jobId} projectId={projectId} jobId={jobId} /></div>}
  </>;
  return <>
    {draft && <DraftTimeline key={scope} projectId={projectId} draft={draft} />}
    <div hidden={Boolean(draft)} style={draft ? undefined : { display: "contents" }}>
      {jobId
        ? <JobTimeline key={jobId} projectId={projectId} jobId={jobId} />
        : <TimelineMessage title="No video yet">{workflow === "highlights" ? "Create AI Highlights from your source video and creative prompt to see the moments here." : "Create your first cut with AI Director to see your story here."}</TimelineMessage>}
    </div>
  </>;
}

export function NarrativeTimeline({ projectId }: { projectId?: string }) {
  const { workflow } = useEditingScope(projectId ?? "");
  return (
    <section className="studio-panel studio-timeline" aria-labelledby="timeline-heading" data-tour="timeline">
      <header className="studio-panelHeader"><h2 id="timeline-heading">{workflow === "highlights" ? "AI Highlight Navigator" : "Timeline"}</h2><span>{workflow === "highlights" ? "Why these moments · Explore and refine" : "Review and refine your edit"}</span></header>
      <div className="studio-timelineBody">
        {workflow !== "highlights" && <div className="studio-trackLabel"><span className="studio-overline">Your story</span><span>Moments in order</span></div>}
        {projectId
          ? <ConnectedTimeline key={projectId} projectId={projectId} />
          : <TimelineMessage title="Every story starts with a first scene">Open a project to see your story here.</TimelineMessage>}
      </div>
    </section>
  );
}
