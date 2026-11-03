"use client";

import { useCaptionStore } from "./captions/store";
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
  if (job.isError) return <p role="alert">We couldn’t check on your video. <button type="button" onClick={() => void job.refetch()}>Check again</button></p>;
  const status = job.data?.status;
  const stage = job.data?.progress?.stage;
  const labels: Record<string, string> = {preparing_media:"Getting your footage ready",extracting_windows:"Finding the moments to use",rendering_video:"Putting your video together",publishing_artifacts:"Saving your video"};
  return <p role="status">Version {revision}: {status === "queued" ? "Waiting to create your video" : status === "running" ? labels[stage ?? ""] ?? "Creating your video" : status === "succeeded" ? "Your video is ready" : status === "failed" ? failureDescription(job.data?.error_code ?? null) : "Checking on your video"}</p>;
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
    if (!saved || !matches) throw new Error("Save this draft before making your video.");
    return renderDraft(projectId, saved.revision);
  }, retry:false, onSuccess: jobId => {useCaptionStore.getState().preview(projectId);setPreview(projectId,jobId);void client.invalidateQueries({queryKey:aiJobKey(projectId,jobId)});void client.invalidateQueries({queryKey:renderVersionsKey(projectId)});}});
  async function reloadSaved() {
    setReloadError(null);
    try {const result = await getSavedDraft(projectId);restore(projectId,result,true);client.setQueryData(savedDraftKey(projectId),result);save.reset();render.reset();}
    catch {setReloadError("We couldn’t reload your saved draft. What you edited here is kept.");}
  }
  return <div className="studio-draftPersistence">
    <p role="status">{matches ? `Saved as version ${saved?.revision}` : "You have unsaved changes"} · {matches && currentRender?.status === "succeeded" ? "Your finished video is ready to watch" : "You haven’t made a video from this draft yet"}</p>
    <div className="studio-draftActions">
      <button type="button" className="button button-secondary" disabled={matches || save.isPending} onClick={() => save.mutate()}>{save.isPending ? "Saving…" : "Save draft"}</button>
      <button type="button" className="button button-primary" disabled={!matches || !draft.cuts.length || render.isPending || currentRender?.status === "queued" || currentRender?.status === "running" || currentRender?.status === "succeeded"} onClick={() => render.mutate()}>{render.isPending ? "Creating your video…" : currentRender?.status === "failed" ? "Try making this video again" : "Make my video"}</button>
    </div>
    {save.isError && <div role="alert"><p>{save.error instanceof ApiError && save.error.status === 409 ? "A newer draft is already saved. What you edited here is kept." : "We couldn’t confirm your draft saved. What you edited here is kept."}</p><button type="button" className="button button-secondary" onClick={() => void reloadSaved()}>Discard my edits and show the saved draft</button></div>}
    {render.isError && <p role="alert">We couldn’t start your video. Check your versions before trying again. <button type="button" onClick={() => void versions.refetch()}>Check versions</button></p>}
    {reloadError && <p role="alert">{reloadError}</p>}
    {versions.isError && <p role="alert">We couldn’t load your video versions. <button type="button" onClick={() => void versions.refetch()}>Try again</button></p>}
    {currentRender && <ManualRenderStatus projectId={projectId} jobId={currentRender.job_id} revision={currentRender.revision} />}
  </div>;
}

export function RenderVersionPicker({projectId}: {projectId:string}) {
  const {manual, versions} = usePreviewJob(projectId);
  const captioned = useCaptionStore(state=>state.previews[projectId]);
  const clearCaptioned = useCaptionStore(state=>state.preview);
  const setPreview = useDraftStore(state=>state.setPreview);
  return <label className="studio-renderPicker">Choose a version to watch <select value={captioned ? `captioned:${captioned.artifactId}` : manual?.job_id ?? ""} onChange={event=>{if(event.target.value.startsWith("captioned:")) return;clearCaptioned(projectId);setPreview(projectId,event.target.value || null);}}>
    {captioned && <option value={`captioned:${captioned.artifactId}`}>{captioned.label}</option>}
    <option value="">Your first cut</option>
    {versions.data?.map(v=><option key={v.job_id} value={v.job_id}>Version {v.revision} · {v.status === "succeeded" ? "ready" : v.status}</option>)}
  </select></label>;
}
