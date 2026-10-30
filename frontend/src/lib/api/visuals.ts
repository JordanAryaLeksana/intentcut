import { aiJobsPath } from "./ai-jobs";
import { ApiError, isProjectId, isRecord, requestJSON, requireUUID } from "./transport";

export interface VisualJob {
  id:string;status:"queued"|"running"|"succeeded"|"failed";error_code:string|null;
  preset:"thumbnail"|"cover"|"poster";operation:"generate"|"edit";model:string;
  source_artifact_id:string|null;source_sha256:string|null;frame_seconds:number|null;
  artifact_id:string|null;size_bytes:number|null;
}
export interface ProjectCover {artifact_id:string;job_id:string;sha256:string;revision:number}
export interface VisualHistory {items:VisualJob[];cover:ProjectCover|null}
export interface VisualRequest {request_id:string;prompt:string;preset:VisualJob["preset"];operation:VisualJob["operation"];source_artifact_id?:string;frame_seconds?:number}
const invalid=():never=>{throw new ApiError("Invalid image service response.",0,"invalid_response");};
const uuid=(value:unknown):value is string=>typeof value==="string"&&isProjectId(value);
const hash=(value:unknown):value is string=>typeof value==="string"&&/^[0-9a-f]{64}$/.test(value);
export function parseVisualHistory(value:unknown):VisualHistory {
  if(!isRecord(value)||!Array.isArray(value.items))return invalid();
  const items=value.items.map((job:unknown):VisualJob=>{
    if(!isRecord(job)||!uuid(job.id)||typeof job.status!=="string"||!["queued","running","succeeded","failed"].includes(job.status)
      ||typeof job.preset!=="string"||!["thumbnail","cover","poster"].includes(job.preset)
      ||(job.operation!=="generate"&&job.operation!=="edit")||job.model!=="muse-image-1.0"
      ||(job.error_code!==null&&typeof job.error_code!=="string")
      ||(job.source_artifact_id!==null&&!uuid(job.source_artifact_id))||(job.source_sha256!==null&&!hash(job.source_sha256))
      ||(job.frame_seconds!==null&&(typeof job.frame_seconds!=="number"||!Number.isFinite(job.frame_seconds)||job.frame_seconds<0))
      ||(job.artifact_id!==null&&!uuid(job.artifact_id))||(job.size_bytes!==null&&(typeof job.size_bytes!=="number"||!Number.isSafeInteger(job.size_bytes)||job.size_bytes<=0)))return invalid();
    if(job.status!=="queued"&&job.status!=="running"&&job.status!=="succeeded"&&job.status!=="failed")return invalid();
    if(job.preset!=="thumbnail"&&job.preset!=="cover"&&job.preset!=="poster")return invalid();
    return {id:job.id,status:job.status,preset:job.preset,operation:job.operation,model:job.model,
      error_code:typeof job.error_code==="string"?job.error_code:null,
      source_artifact_id:typeof job.source_artifact_id==="string"?job.source_artifact_id:null,
      source_sha256:typeof job.source_sha256==="string"?job.source_sha256:null,
      frame_seconds:typeof job.frame_seconds==="number"?job.frame_seconds:null,
      artifact_id:typeof job.artifact_id==="string"?job.artifact_id:null,size_bytes:typeof job.size_bytes==="number"?job.size_bytes:null};
  });
  let cover:ProjectCover|null=null;
  if(value.cover!==null){const c=value.cover;if(!isRecord(c)||!uuid(c.artifact_id)||!uuid(c.job_id)||!hash(c.sha256)||typeof c.revision!=="number"||!Number.isSafeInteger(c.revision)||c.revision<1)return invalid();cover={artifact_id:c.artifact_id,job_id:c.job_id,sha256:c.sha256,revision:c.revision};}
  return {items,cover};
}
const path=(project:string)=>`${aiJobsPath(project)}/visuals`;
export async function getVisualHistory(project:string,signal?:AbortSignal):Promise<VisualHistory>{return parseVisualHistory(await requestJSON(path(project),{signal}));}
export async function submitVisual(project:string,body:VisualRequest):Promise<string>{
  requireUUID(body.request_id,"request");if(body.source_artifact_id)requireUUID(body.source_artifact_id,"source");
  const value=await requestJSON(path(project),{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify(body)});
  if(!isRecord(value)||!uuid(value.id))return invalid();return value.id;
}
export async function setProjectCover(project:string,artifact:string,revision:number):Promise<void>{
  const result=await requestJSON(`${path(project)}/cover`,{method:"PUT",headers:{"Content-Type":"application/json"},body:JSON.stringify({artifact_id:requireUUID(artifact,"image"),expected_revision:revision})});
  if(!isRecord(result)||result.artifact_id!==artifact||!uuid(result.job_id)||!hash(result.sha256)||typeof result.revision!=="number"||!Number.isSafeInteger(result.revision))return invalid();
}
