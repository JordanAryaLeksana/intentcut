"use client";

import { useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { ApiError } from "@/lib/api/transport";
import { getSavedDraft, renderDraft, saveDraft } from "@/lib/api/editing";
import { draftMatchesSaved, useDraftStore, type TimelineDraft } from "./store/use-draft-store";
import { renderVersionsKey, savedDraftKey, useRenderVersions, usePreviewJob } from "./use-editing";
import { aiJobKey } from "./ai-director/hooks/use-ai-job-status";
import { useAIJobStatus } from "./ai-director/hooks/use-ai-job-status";
import { failureDescription } from "./ai-director/processing-state";

function ManualRenderStatus({ projectId, jobId, revision }: {projectId:string; jobId:string; revision:number}) {
  const job = useAIJobStatus(projectId, jobId);
  if (job.isError) return <p role="alert">Could not refresh render status. <button type="button" onClick={() => void job.refetch()}>Retry status</button></p>;
  const status = job.data?.status;
  const stage = job.data?.progress?.stage;
  const labels: Record<string, string> = {preparing_media:"Verifying source footage",extracting_windows:"Extracting saved cut ranges",rendering_video:"Rendering and validating MP4",publishing_artifacts:"Publishing video and frame manifest"};
  return <p role="status">Revision {revision}: {status === "queued" ? "Render accepted · waiting" : status === "running" ? labels[stage ?? ""] ?? "Render processing" : status === "succeeded" ? "Rendered successfully" : status === "failed" ? failureDescription(job.data?.error_code ?? null) : "Checking render status"}</p>;
}

export function DraftPersistence({projectId, draft}: {projectId:string; draft:TimelineDraft}) {
  const client = useQueryClient();
  const saved = useDraftStore(state => state.savedByProject[projectId]);
  const { saved: markSaved, restore, setPreview } = useDraftStore();
  const versions = useRenderVersions(projectId);
  const [reloadError, setReloadError] = useState<string | null>(null);
  const matches = draftMatchesSaved(draft, saved);
  const currentRender = versions.data?.find(v => v.revision === saved?.revision);
  const save = useMutation({mutationFn: () => saveDraft(projectId, {expected_revision:saved?.revision ?? 0,
    base_job_id:draft.base.jobId,base_artifact_id:draft.base.artifactId,window_indices:draft.cuts.map(c=>c.window_index)}),
    retry:false, onSuccess: result => {markSaved(projectId,result);client.setQueryData(savedDraftKey(projectId),result);}});
  const render = useMutation({mutationFn: () => {
    if (!saved || !matches) throw new Error("Save this draft before rendering.");
    return renderDraft(projectId, saved.revision);
  }, retry:false, onSuccess: jobId => {setPreview(projectId,jobId);void client.invalidateQueries({queryKey:aiJobKey(projectId,jobId)});void client.invalidateQueries({queryKey:renderVersionsKey(projectId)});}});
  async function reloadSaved() {
    setReloadError(null);
    try {const result = await getSavedDraft(projectId);restore(projectId,result,true);client.setQueryData(savedDraftKey(projectId),result);save.reset();render.reset();}
    catch {setReloadError("Could not reload the saved draft. Your local edits are retained.");}
  }
  return <div className="studio-draftPersistence">
    <p role="status">{matches ? `Saved revision ${saved?.revision}` : "Unsaved draft changes"} · {matches && currentRender?.status === "succeeded" ? "Rendered version available" : "Current draft is not rendered"}</p>
    <div className="studio-draftActions">
      <button type="button" className="button button-secondary" disabled={matches || save.isPending} onClick={() => save.mutate()}>{save.isPending ? "Saving…" : "Save Draft"}</button>
      <button type="button" className="button button-primary" disabled={!matches || !draft.cuts.length || render.isPending || currentRender?.status === "queued" || currentRender?.status === "running" || currentRender?.status === "succeeded"} onClick={() => render.mutate()}>{render.isPending ? "Submitting render…" : currentRender?.status === "failed" ? "Retry saved render" : "Render Updated Cut"}</button>
    </div>
    {save.isError && <div role="alert"><p>{save.error instanceof ApiError && save.error.status === 409 ? "Save conflict: a newer draft exists. Local edits were retained." : "Draft save was not confirmed. Local edits were retained."}</p><button type="button" className="button button-secondary" onClick={() => void reloadSaved()}>Discard local edits and reload saved draft</button></div>}
    {render.isError && <p role="alert">Render admission was not confirmed. Refresh versions before retrying. <button type="button" onClick={() => void versions.refetch()}>Refresh versions</button></p>}
    {reloadError && <p role="alert">{reloadError}</p>}
    {versions.isError && <p role="alert">Render versions unavailable. <button type="button" onClick={() => void versions.refetch()}>Retry versions</button></p>}
    {currentRender && <ManualRenderStatus projectId={projectId} jobId={currentRender.job_id} revision={currentRender.revision} />}
  </div>;
}

export function RenderVersionPicker({projectId}: {projectId:string}) {
  const {manual, versions} = usePreviewJob(projectId);
  const setPreview = useDraftStore(state=>state.setPreview);
  return <label className="studio-renderPicker">Preview version <select value={manual?.job_id ?? ""} onChange={event=>setPreview(projectId,event.target.value || null)}>
    <option value="">Original AI first cut</option>
    {versions.data?.map(v=><option key={v.job_id} value={v.job_id}>Draft revision {v.revision} · {v.status}</option>)}
  </select></label>;
}
