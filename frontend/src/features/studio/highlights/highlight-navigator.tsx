"use client";

import { useEffect, useRef } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { createHighlightJob } from "@/lib/api/highlights";
import { listAIJobs } from "@/lib/api/ai-jobs";
import { ApiError } from "@/lib/api/transport";
import { useEditingScope } from "../workflow";
import { useProjectMedia } from "../media/hooks/use-project-media";
import { useAIJobStatus } from "../ai-director/hooks/use-ai-job-status";
import { useActiveJobId, useEditorStore } from "../store/use-editor-store";
import { useDraftStore } from "../store/use-draft-store";
import { useEditableFirstCut } from "../ai-director/hooks/use-editable-first-cut";
import { RevisionChat } from "../ai-director/revision-chat";
import { DirectorProcessingStatus } from "../ai-director/director-processing-status";
import { useHighlightBrief } from "./use-highlight-brief";
import { formatTimestamp } from "./highlight-format";
import { HighlightSelectedStory } from "./highlight-selected-story";
import "./highlights.css";

export const highlightJobsKey = (projectId: string) => ["projects", projectId, "highlight-jobs"] as const;

export function HighlightNavigator({ projectId }: { projectId?: string }) {
  return projectId ? <ConnectedHighlights key={projectId} projectId={projectId} /> : <p>Open a project to create AI Highlights.</p>;
}

function ConnectedHighlights({ projectId }: { projectId: string }) {
  const { scope } = useEditingScope(projectId);
  const media = useProjectMedia(projectId);
  const client = useQueryClient();
  const { brief: { sourceId, intent, targetSeconds }, update } = useHighlightBrief(projectId);
  const request = useRef<{ signature: string; id: string } | null>(null);
  const submitLock = useRef(false);
  const acceptedHere = useRef<string | null>(null);
  const activeJobId = useActiveJobId(projectId);
  const setActiveJob = useEditorStore(state => state.setActiveJob);
  const recovery = useQuery({ queryKey: highlightJobsKey(projectId),
    queryFn: ({ signal }) => listAIJobs(projectId, signal, "highlights"), retry: false,
    refetchInterval: query => query.state.data?.some(j => j.status === "queued" || j.status === "running") ? 2000 : false,
  });
  useEffect(() => {
    if (!recovery.isSuccess || submitLock.current) return;
    const jobs = recovery.data.filter(j => j.pipeline_version === "highlight_v1");
    if (acceptedHere.current && !jobs.some(j => j.id === acceptedHere.current)) return;
    const active = jobs.find(j => j.status === "queued" || j.status === "running") ?? jobs[0];
    if (active) setActiveJob(scope, active.id);
  }, [recovery.data, recovery.isSuccess, scope, setActiveJob]);
  const status = useAIJobStatus(projectId, activeJobId);
  const editable = useEditableFirstCut(projectId, activeJobId, recovery.data ?? []);
  const source = media.data?.find(item => item.id === sourceId) ?? media.data?.[0];
  const busy = status.data?.status === "queued" || status.data?.status === "running" ||
    recovery.data?.some(job => job.status === "queued" || job.status === "running");
  const generate = useMutation({
    mutationFn: async () => {
      if (!source || !intent.trim()) throw Error("Choose footage and describe the highlights you want.");
      const body = { kind: "highlight" as const, intent: intent.trim(), target_seconds: targetSeconds, media_ids: [source.id] as [string] };
      const signature = JSON.stringify(body);
      const storageKey = `intentcut:highlight-request:${projectId}`;
      if (!request.current) {
        try {
          const previous = JSON.parse(sessionStorage.getItem(storageKey) ?? "null");
          if (previous?.signature === signature && typeof previous.id === "string") request.current = previous;
        } catch { /* Optional recovery. */ }
      }
      if (request.current?.signature !== signature) request.current = { signature, id: crypto.randomUUID() };
      try { sessionStorage.setItem(storageKey, JSON.stringify(request.current)); } catch { /* Optional recovery. */ }
      return createHighlightJob(projectId, { ...body, request_id: request.current.id });
    },
    retry: false,
    onSuccess: accepted => {
      acceptedHere.current = accepted.id;
      setActiveJob(scope, accepted.id);
      useDraftStore.getState().setPreview(scope, null);
      request.current = null;
      try { sessionStorage.removeItem(`intentcut:highlight-request:${projectId}`); } catch { /* Optional recovery. */ }
      void client.invalidateQueries({ queryKey: highlightJobsKey(projectId) });
    },
    onError: () => { void recovery.refetch(); },
    onSettled: () => { submitLock.current = false; },
  });
  return <div className="highlight-navigator studio-directorBody">
    <header className="studio-panelHeader"><h2>AI Highlights</h2><span>Long video → focused story</span></header>
    <p className="highlight-intro">Find the moments that matter. Describe your story and we’ll assemble a draft you can refine.</p>
    <form className="highlight-section" onSubmit={event => {
      event.preventDefault();
      if (submitLock.current || generate.isPending || busy || !recovery.isSuccess) return;
      submitLock.current = true; generate.mutate();
    }}>
      <label className="highlight-label" htmlFor="highlight-source">Long video</label>
      {media.isError ? <p role="alert">Footage could not be loaded. <button type="button" onClick={() => void media.refetch()}>Try again</button></p>
        : !media.data?.length ? <p>{media.isPending ? "Loading footage…" : "Upload a video in Media Library to begin."}</p>
        : <select id="highlight-source" value={source?.id ?? ""} disabled={busy || generate.isPending} onChange={e => update({ sourceId: e.target.value })}>{media.data.map(item => <option key={item.id} value={item.id}>{item.original_filename} · {formatTimestamp(item.duration_seconds)}</option>)}</select>}
      <label className="highlight-label" htmlFor="highlight-intent">What should your highlights show?</label>
      <textarea id="highlight-intent" required maxLength={1000} rows={3} value={intent} disabled={busy || generate.isPending} onChange={e => update({ intent: e.target.value })} placeholder="Make a 30-second recap of the final award presentation, especially the winner lifting the trophy." />
      <label className="highlight-label" htmlFor="highlight-target">Output duration (seconds, up to 120)</label>
      <input id="highlight-target" type="number" min={1} max={120} required value={targetSeconds} disabled={busy || generate.isPending} onChange={e => update({ targetSeconds: Number(e.target.value) })} />
      <div className="highlight-presets" aria-label="Duration presets">{[15, 30, 60, 120].map(seconds => <button key={seconds} type="button" aria-pressed={targetSeconds === seconds} disabled={busy || generate.isPending} onClick={() => update({ targetSeconds: seconds })}>{seconds}s</button>)}</div>
      <p className="highlight-note">We automatically choose and assemble moments for your prompt. The duration is a maximum; a shorter edit may be returned.</p>
      <button className="button button-primary" type="submit" disabled={!source || !intent.trim() || busy || generate.isPending || !recovery.isSuccess || !Number.isFinite(targetSeconds) || targetSeconds < 1 || targetSeconds > 120}>{busy ? "Creating highlights…" : generate.isPending ? "Starting…" : "Create highlights"}</button>
      {generate.isError && <p role="alert">{generate.error instanceof ApiError && generate.error.status === 409 ? "A highlight request already exists. Check processing status before retrying." : generate.error instanceof ApiError && generate.error.status > 0 && generate.error.status < 500 ? generate.error.message : "We couldn’t confirm the request. Check processing status, then retry with the same prompt."}</p>}
      {recovery.isError && <p role="alert">We couldn’t recover your Highlights jobs. <button type="button" onClick={() => void recovery.refetch()}>Check again</button></p>}
      <details className="processing-jobId"><summary>How much of my video is checked?</summary><p>We sample up to 48 frames across the entire source and up to 24 more around promising matches. Brief events between samples and dialogue-only moments may be missed. Selected clips receive additional video analysis. Your source timestamps are preserved.</p></details>
    </form>
    <DirectorProcessingStatus projectId={projectId} firstCutJobId={activeJobId} />
    {status.data?.status === "succeeded" && <p className="highlight-success" role="status">Your highlights are ready. Review AI-selected moments and their relevance scores in the Navigator below the preview. Save your changes before rendering again.</p>}
    {editable && <RevisionChat projectId={projectId} />}
    <HighlightSelectedStory projectId={projectId} />
  </div>;
}
