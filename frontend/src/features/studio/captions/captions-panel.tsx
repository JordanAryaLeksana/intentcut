"use client";

import { useEffect, useRef, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ApiError } from "@/lib/api/transport";
import { createCaptionSet, exportCaptions, getCaptionSet, getVideoCaptions, saveCaptionSet, transcribeVideo, type CaptionJob, type CaptionSet, type VideoCaptions } from "@/lib/api/captions";
import { listAIArtifacts } from "@/lib/api/artifacts";
import { usePreviewJob } from "../use-editing";
import { useAIArtifacts } from "../ai-director/hooks/use-ai-artifacts";
import { useAIJobStatus } from "../ai-director/hooks/use-ai-job-status";
import { STAGE_COPY, failureDescription } from "../ai-director/processing-state";
import { captionDirty, captionScope, useCaptionStore, type CaptionDraft } from "./store";

export const videoCaptionsKey = (project: string, video: string) => ["projects", project, "video-captions", video] as const;
export function captionPolling(data?: VideoCaptions): number | false {
  return data?.jobs.some(j=>j.status==="queued" || j.status==="running") ? 2000 : false;
}
function message(error: unknown) {
  if (error instanceof ApiError && error.status===409) return "Conflict: the saved caption revision changed. Your edits are retained. Reload explicitly to discard them.";
  return error instanceof Error ? error.message : "Request was not confirmed. Refresh before retrying.";
}
function CaptionJobStatus({project,job}:{project:string;job:CaptionJob}) {
  const status=useAIJobStatus(project,job.id);
  const value=status.data?.status ?? job.status;
  const title=job.kind==="caption_transcribe_v1" ? "Transcription" : `${job.enabled_cues===0 ? "Unchanged export" : "Caption export"} r${job.caption_revision}`;
  return <div role="status" className="studio-captionJob">
    <strong>{title}</strong>: {value==="queued" ? "Accepted · waiting" : value==="running" ? (status.data?.progress?.stage==="publishing_artifacts" ? "Publishing caption output" : STAGE_COPY[status.data?.progress?.stage ?? "preparing_media"].title) : value==="succeeded" ? "Succeeded" : failureDescription(status.data?.error_code ?? job.error_code)}
    {status.isError && <><span> Status refresh unavailable.</span><button type="button" onClick={()=>void status.refetch()}>Retry status</button></>}
  </div>;
}
export function CaptionFields({draft,saving=false,exporting=false,onChange,onSave,onExport}: {
  draft: CaptionDraft; saving?:boolean; exporting?:boolean;
  onChange:(index:number,patch:Partial<{text:string;enabled:boolean}>)=>void;
  onSave:()=>void;onExport:()=>void;
}) {
  const dirty=captionDirty(draft);
  return <>
    <p role="status">{dirty ? "Unsaved caption changes" : `Saved caption revision ${draft.saved.revision}`} · Preview text is not burned into the MP4.</p>
    {!draft.edits.some(c=>c.enabled) && <p>{draft.edits.length ? "No enabled cues." : "No speech cues in this transcript."} Export will preserve the video without adding subtitles.</p>}
    <ol className="studio-captionCues">
      {draft.edits.map((cue,i)=> <li key={cue.index}>
        <div className="studio-captionCueHeader"><label><input type="checkbox" checked={cue.enabled} onChange={e=>onChange(cue.index,{enabled:e.target.checked})} /> Cue {i+1}</label><span className="technical">{(draft.saved.cues[i].start_ms/1000).toFixed(3)}–{(draft.saved.cues[i].end_ms/1000).toFixed(3)} s</span></div>
        <label htmlFor={`caption-text-${draft.saved.id}-${i}`} className="sr-only">Text for cue {i+1}</label>
        <textarea id={`caption-text-${draft.saved.id}-${i}`} value={cue.text} maxLength={2000} rows={3} onChange={e=>onChange(cue.index,{text:e.target.value})} aria-invalid={cue.enabled && !cue.text.trim()} />
        {cue.enabled && !cue.text.trim() && <p role="alert">Enter text or disable this cue.</p>}
      </li>)}
    </ol>
    <div className="studio-captionActions">
      <button type="button" className="button button-secondary" disabled={!dirty || saving || draft.edits.some(c=>c.enabled&&!c.text.trim())} onClick={()=>onSave()}>{saving?"Saving…":"Save Captions"}</button>
      <button type="button" className="button button-primary" disabled={dirty || saving || exporting} onClick={()=>onExport()}>{exporting?"Submitting export…":"Export Captioned MP4"}</button>
    </div>
  </>;
}
export function CaptionEditor({project,video,saved,onRefresh}:{project:string;video:string;saved:CaptionSet;onRefresh:()=>void}) {
  const scope=captionScope(project,video,saved.id);
  const draft=useCaptionStore(state=>state.drafts[scope]);
  const {receive,change,saved:markSaved}=useCaptionStore();
  const [reloadError,setReloadError]=useState<string|null>(null);
  useEffect(()=>receive(scope,saved),[scope,saved,receive]);
  const save=useMutation({mutationFn:async()=> {
    if (!draft) throw new Error("Caption draft unavailable.");
    return saveCaptionSet(project,draft.saved.id,draft.saved.revision,draft.edits);
  },retry:false,onSuccess:result=>{markSaved(scope,result);onRefresh();}});
  const exportJob=useMutation({mutationFn:async()=> {
    if (!draft || captionDirty(draft)) throw new Error("Save captions before exporting.");
    return exportCaptions(project,draft.saved.id,draft.saved.revision);
  },retry:false,onSuccess:onRefresh});
  if (!draft) return <p role="status">Loading saved caption revision…</p>;
  async function reload() {
    try {receive(scope,await getCaptionSet(project,saved.id),true);save.reset();setReloadError(null);onRefresh();}
    catch {setReloadError("Reload failed. Your local caption text is retained.");}
  }
  return <div className="studio-captionEditor">
    <CaptionFields draft={draft} saving={save.isPending} exporting={exportJob.isPending} onChange={(index,patch)=>change(scope,index,patch)} onSave={()=>save.mutate()} onExport={()=>exportJob.mutate()} />
    {save.isError && <div role="alert"><p>{message(save.error)}</p><button type="button" className="button button-secondary" onClick={()=>void reload()}>Discard local changes and reload saved captions</button></div>}
    {exportJob.isError && <p role="alert">{message(exportJob.error)}</p>}
    {reloadError && <p role="alert">{reloadError}</p>}
  </div>;
}
function VideoCaptionsPanel({project,video}:{project:string;video:string}) {
  const client=useQueryClient();
  const alive=useRef(true);
  useEffect(()=>{alive.current=true;return()=>{alive.current=false;};},[]);
  const state=useQuery({queryKey:videoCaptionsKey(project,video),queryFn:({signal})=>getVideoCaptions(project,video,signal),retry:false,refetchOnWindowFocus:true,
    refetchInterval:q=>q.state.error ? false : captionPolling(q.state.data)});
  const refresh=()=>{void client.invalidateQueries({queryKey:videoCaptionsKey(project,video)});};
  const [requestId]=useState(()=>crypto.randomUUID());
  const [previewError,setPreviewError]=useState<string|null>(null);
  const setPreview=useCaptionStore(s=>s.preview);
  const transcribe=useMutation({mutationFn:()=>transcribeVideo(project,video,requestId),retry:false,onSuccess:refresh});
  const create=useMutation({mutationFn:(id:string)=>createCaptionSet(project,id),retry:false,onSuccess:refresh});
  async function preview(job:CaptionJob) {
    try {
      const artifacts=await listAIArtifacts(project,job.id);
      const artifact=artifacts.items.find(a=>a.kind==="rendition" && a.parent_artifact_id===video);
      if (!artifact) throw new Error("Captioned video artifact is not available yet. Refresh outputs.");
      if (!alive.current) return;
      setPreview(project,{jobId:job.id,artifactId:artifact.id,label:`${job.enabled_cues===0?"Unchanged MP4 (no active cues)":"Captioned MP4"} · caption revision ${job.caption_revision}`});
      setPreviewError(null);
    } catch(e){if(alive.current)setPreviewError(message(e));}
  }
  if (state.isPending) return <p role="status">Loading captions for this video…</p>;
  if (state.isError) return <div role="alert"><p>Captions unavailable. The API requires migrations 004 and 005.</p><button type="button" className="button button-secondary" onClick={()=>void state.refetch()}>Retry captions</button></div>;
  const data=state.data;
  const saved=data.sets[0];
  const transcription=data.jobs.find(j=>j.kind==="caption_transcribe_v1");
  const exports=data.jobs.filter(j=>j.kind==="caption_burn_v1");
  return <>
    <p className="studio-storyboardNote">Captions belong to this exact video version. Selecting another video loads its own captions.</p>
    <p className="studio-sourceId technical">Video {video}</p>
    {!transcription && !data.transcriptions.length && <><p>Muse Voice processes the audio. This action may use paid model credits when a Voice worker is enabled.</p><button type="button" className="button button-primary" disabled={transcribe.isPending} onClick={()=>transcribe.mutate()}>{transcribe.isPending?"Submitting…":"Transcribe Video"}</button></>}
    {transcribe.isError && <p role="alert">{message(transcribe.error)} <button type="button" onClick={()=>void state.refetch()}>Refresh accepted jobs</button></p>}
    {transcription && <CaptionJobStatus project={project} job={transcription} />}
    {!saved && data.transcriptions[0] && <button type="button" className="button button-secondary" disabled={create.isPending} onClick={()=>create.mutate(data.transcriptions[0].id)}>{create.isPending?"Creating caption set…":"Edit transcript"}</button>}
    {create.isError && <p role="alert">{message(create.error)}</p>}
    {saved && <CaptionEditor key={saved.id} project={project} video={video} saved={saved} onRefresh={refresh} />}
    {exports.map(job=><div key={job.id} className="studio-captionOutput"><CaptionJobStatus project={project} job={job} />{job.status==="succeeded" && <button type="button" className="button button-secondary" onClick={()=>void preview(job)}>Preview / download {job.enabled_cues===0 ? "unchanged" : "caption"} export r{job.caption_revision}</button>}</div>)}
    {previewError && <p role="alert">{previewError}</p>}
  </>;
}
function ConnectedCaptionsPanel({projectId}:{projectId:string}) {
  const {jobId:base}=usePreviewJob(projectId ?? "");
  const override=useCaptionStore(s=>projectId?s.previews[projectId]:undefined);
  const jobId=override?.jobId ?? base;
  const artifacts=useAIArtifacts(projectId ?? "",jobId);
  const video=artifacts.data?.items.find(a=>override ? a.id===override.artifactId : a.kind==="video");
  return <section className="studio-captions" aria-labelledby="captions-heading">
    <header className="studio-panelHeader"><h2 id="captions-heading">Captions</h2><span>Version-bound subtitles</span></header>
    <div className="studio-captionBody">{!projectId ? <p>Open a project to work with captions.</p> : artifacts.isError ? <p role="alert">Unable to load video metadata. <button type="button" onClick={()=>void artifacts.refetch()}>Retry video metadata</button></p> : !video ? <p>Choose a successfully rendered video in the Program Monitor.</p> : <VideoCaptionsPanel key={`${projectId}:${video.id}`} project={projectId} video={video.id} />}</div>
  </section>;
}

export function CaptionsPanel({projectId}:{projectId?:string}) {
  return projectId ? <ConnectedCaptionsPanel key={projectId} projectId={projectId} /> : <section className="studio-captions"><header className="studio-panelHeader"><h2>Captions</h2></header><p>Open a project to work with captions.</p></section>;
}
