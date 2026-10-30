"use client";

import Image from "next/image";
import { useEffect, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ApiError } from "@/lib/api/transport";
import { downloadAIArtifact } from "@/lib/api/artifacts";
import { getVisualHistory, setProjectCover, submitVisual, type VisualHistory, type VisualJob, type VisualRequest } from "@/lib/api/visuals";
import { useCaptionStore } from "../captions/store";
import { monitorVideo, visualReference } from "../monitor-video";
import { usePreviewJob } from "../use-editing";
import { useAIArtifacts } from "../ai-director/hooks/use-ai-artifacts";
import { useAIJobStatus } from "../ai-director/hooks/use-ai-job-status";

export const visualHistoryKey=(project:string)=>["projects",project,"visual-assets"] as const;
export function visualPolling(value?:VisualHistory):number|false{return value?.items.some(j=>j.status==="queued"||j.status==="running")?2000:false;}
function errorText(error:unknown){
  if(error instanceof ApiError&&error.status===409)return "The image request or cover changed. Refresh before retrying; local prompt is retained.";
  return "The image operation could not be confirmed. Refresh existing jobs before retrying.";
}
export function VisualImage({project,job,artifact,alt}:{project:string;job:string;artifact:string;alt:string}){
  const key=`${project}:${job}:${artifact}`;
  const [result,setResult]=useState<{key:string;url?:string;error?:boolean}>({key:""});
  const [attempt,setAttempt]=useState(0);
  useEffect(()=>{
    const abort=new AbortController();let url:string|undefined;
    void downloadAIArtifact(project,job,artifact,abort.signal).then(blob=>{
      if(abort.signal.aborted)return;
      if(blob.type!=="image/png"||blob.size>16*1024*1024)throw new Error("Invalid image");
      url=URL.createObjectURL(blob);setResult({key,url});
    }).catch(()=>{if(!abort.signal.aborted)setResult({key,error:true});});
    return()=>{abort.abort();if(url)URL.revokeObjectURL(url);};
  },[project,job,artifact,key,attempt]);
  if(result.key!==key||(!result.url&&!result.error))return <p role="status">Loading verified image…</p>;
  if(result.error)return <p role="alert">Image unavailable. <button type="button" className="button button-secondary" onClick={()=>setAttempt(a=>a+1)}>Retry image</button></p>;
  return <div className="studio-visualImage"><div className="studio-visualFrame"><Image src={result.url ?? ""} alt={alt} fill unoptimized sizes="(max-width: 600px) 90vw, 340px" /></div><a href={result.url} download={`intentcut-${artifact}.png`} className="button button-secondary">Download image</a></div>;
}
function VisualStatus({project,job}:{project:string;job:VisualJob}){
  const observed=useAIJobStatus(project,job.id);
  const status=observed.data?.status??job.status;
  const stage=observed.data?.progress?.stage;
  let copy=status==="queued"?"Accepted · waiting":status==="succeeded"?"Image published":status==="failed"?"Image processing failed. No automatic paid retry was submitted.":stage==="validating_image"?"Validating image bytes":stage==="publishing_artifacts"?"Publishing image":stage==="preparing_media"?"Verifying reference":"Muse Image is processing";
  if(status==="failed"&&(observed.data?.error_code??job.error_code)==="image_outcome_unknown")copy="Provider outcome uncertain. Automatic retry is disabled to avoid duplicate charges.";
  return <p role="status">{copy}{observed.isError&&<> Status refresh unavailable. <button type="button" onClick={()=>void observed.refetch()}>Retry status</button></>}</p>;
}
export function VisualPromptForm({prompt,setPrompt,preset,setPreset,operation,setOperation,source,setSource,frame,setFrame,video,images,pending,onSubmit}:{
  prompt:string;setPrompt:(v:string)=>void;preset:VisualJob["preset"];setPreset:(v:VisualJob["preset"])=>void;
  operation:VisualJob["operation"];setOperation:(v:VisualJob["operation"])=>void;source:string;setSource:(v:string)=>void;
  frame:string;setFrame:(v:string)=>void;video?:string;images:VisualJob[];pending:boolean;onSubmit:()=>void;
}){
  return <form className="studio-visualForm" onSubmit={e=>{e.preventDefault();onSubmit();}}>
    <label htmlFor="visual-prompt">Image instruction<textarea id="visual-prompt" value={prompt} maxLength={2000} rows={4} onChange={e=>setPrompt(e.target.value)} required /></label>
    <label htmlFor="visual-preset">Creative preset<select id="visual-preset" value={preset} onChange={e=>{const v=e.target.value;if(v==="thumbnail"||v==="cover"||v==="poster")setPreset(v);}}><option value="thumbnail">Thumbnail · landscape</option><option value="cover">Cinematic cover · landscape</option><option value="poster">Poster · portrait</option></select></label>
    <p className="studio-storyboardNote">Presets suggest aspect ratio; actual generated pixel dimensions are model-dependent. These are still images, not video title cards.</p>
    <label htmlFor="visual-operation">Mode<select id="visual-operation" value={operation} onChange={e=>setOperation(e.target.value==="edit"?"edit":"generate")}><option value="generate">Generate from text</option><option value="edit">Edit an authorized image/frame</option></select></label>
    {operation==="edit"&&<><label htmlFor="visual-source">Reference asset<select id="visual-source" value={source} onChange={e=>setSource(e.target.value)} required><option value="">Choose reference</option>{video&&<option value={video}>Current rendered video frame</option>}{images.filter(i=>i.artifact_id).map(i=><option key={i.id} value={i.artifact_id??""}>{i.preset} · {i.artifact_id?.slice(0,8)}</option>)}</select></label>{source===video&&<label htmlFor="visual-frame">Frame position (seconds)<input id="visual-frame" type="number" min="0" max="600" step="0.001" value={frame} onChange={e=>setFrame(e.target.value)} required /></label>}</>}
    <p>This explicit action may use paid Muse Image credits when an image worker is enabled.</p>
    <button type="submit" className="button button-primary" disabled={pending||!prompt.trim()||(operation==="edit"&&!source)}>{pending?"Submitting…":operation==="edit"?"Request image edit":"Generate image"}</button>
  </form>;
}
function ConnectedVisuals({project}:{project:string}){
  const client=useQueryClient();const {jobId:baseJob}=usePreviewJob(project);
  const override=useCaptionStore(state=>state.previews[project]);
  const jobId=override?.jobId??baseJob;
  const artifacts=useAIArtifacts(project,jobId);
  const video=monitorVideo(artifacts.data?.items??[],override?.artifactId)?.id;
  const history=useQuery({queryKey:visualHistoryKey(project),queryFn:({signal})=>getVisualHistory(project,signal),retry:false,refetchOnWindowFocus:true,refetchInterval:q=>q.state.error?false:visualPolling(q.state.data)});
  const [prompt,setPrompt]=useState("");const [preset,setPreset]=useState<VisualJob["preset"]>("thumbnail");
  const [operation,setOperation]=useState<VisualJob["operation"]>("generate");const [source,setSource]=useState("");const [frame,setFrame]=useState("0");
  const selectedSource=visualReference(source,video);
  const [requestId,setRequestId]=useState(()=>crypto.randomUUID());
  const refresh=()=>void client.invalidateQueries({queryKey:visualHistoryKey(project)});
  const submission=useMutation({mutationFn:()=>{
    const body:VisualRequest={request_id:requestId,prompt,preset,operation};
    if(operation==="edit"){body.source_artifact_id=selectedSource;if(selectedSource===video)body.frame_seconds=Number(frame);}
    return submitVisual(project,body);
  },retry:false,onSuccess:()=>{setRequestId(crypto.randomUUID());refresh();}});
  const selection=useMutation({mutationFn:(id:string)=>setProjectCover(project,id,history.data?.cover?.revision??0),retry:false,onSuccess:refresh});
  if(history.isPending)return <p role="status">Loading saved visual assets…</p>;
  if(history.isError)return <div role="alert"><p>AI Visuals is unavailable. Check the local API and required schema migrations.</p><button type="button" className="button button-secondary" onClick={()=>void history.refetch()}>Retry assets</button></div>;
  const data=history.data;
  return <div className="studio-visualBody">
    {data.cover&&<article><h3>Current project cover · saved revision {data.cover.revision}</h3><VisualImage key={data.cover.artifact_id} project={project} job={data.cover.job_id} artifact={data.cover.artifact_id} alt="Saved project cover" /></article>}
    <VisualPromptForm prompt={prompt} setPrompt={setPrompt} preset={preset} setPreset={setPreset} operation={operation} setOperation={setOperation} source={selectedSource} setSource={value=>setSource(value===video?"current-video":value)} frame={frame} setFrame={setFrame} video={video} images={data.items} pending={submission.isPending||data.items.some(j=>j.status==="queued"||j.status==="running")} onSubmit={()=>submission.mutate()} />
    {submission.isError&&<p role="alert">{errorText(submission.error)} <button type="button" onClick={()=>void history.refetch()}>Refresh accepted requests</button></p>}
    {selection.isError&&<p role="alert">{errorText(selection.error)} <button type="button" onClick={()=>void history.refetch()}>Refresh cover</button></p>}
    <h3>Saved assets</h3>
    {!data.items.length&&<p>No generated images yet.</p>}
    {data.items.map(job=><article key={job.id} className="studio-visualAsset"><h4>{job.preset} · {job.operation}</h4><p>Muse Image 1.0{job.source_artifact_id?` · reference ${job.source_artifact_id.slice(0,8)}`:" · text generated"}{job.frame_seconds!==null?` · frame at ${job.frame_seconds}s`:""}</p><VisualStatus project={project} job={job} />{job.status==="succeeded"&&job.artifact_id&&<><VisualImage project={project} job={job.id} artifact={job.artifact_id} alt={`${job.preset} generated by Muse Image`} /><button type="button" className="button button-primary" disabled={selection.isPending||data.cover?.artifact_id===job.artifact_id} onClick={()=>selection.mutate(job.artifact_id??"")}>{data.cover?.artifact_id===job.artifact_id?"Current cover":"Set as Cover"}</button></>}</article>)}
  </div>;
}
export function VisualsPanel({projectId}:{projectId?:string}){return <section className="studio-visuals"><header className="studio-panelHeader"><h2>AI Visuals</h2><span>Images / project cover</span></header>{projectId?<ConnectedVisuals key={projectId} project={projectId}/>:<p>Open a project to create visual assets.</p>}</section>;}
