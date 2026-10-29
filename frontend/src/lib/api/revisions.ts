import { ApiError, isProjectId, isRecord, requestJSON, requireUUID } from "./transport";
import type { AIJobProgress, AIJobStatus } from "./contracts";
import { parseJobProgress } from "./job-progress";
import { parseSavedDraft, type SavedDraft } from "./editing";

export type ProposalState = "pending" | "accepted" | "rejected" | "stale" | "failed";
export interface RevisionProposal {
  id: string; draft_id: string; base_revision: number; base_job_id: string; base_artifact_id: string;
  instruction: string; state: ProposalState; job_status: AIJobStatus; error_code: string | null;
  before: number[]; after: number[] | null; explanation: string | null;
  reasons: {window_index:number; reason:string}[];
  changes: {removed:number[]; reordered:boolean}; applied_revision:number | null;
  progress: AIJobProgress | null;
}
const path = (projectId:string) => `/projects/${requireUUID(projectId,"project")}/edit-draft/proposals`;
function invalid(): never {throw new ApiError("Invalid revision proposal response.",0,"invalid_response");}
function indices(value:unknown): value is number[] {return Array.isArray(value) && value.length<=12 && value.every(i=>Number.isSafeInteger(i)&&i>=0) && new Set(value).size===value.length;}
const subset=(after:number[],before:number[])=>after.every(i=>before.includes(i));
export function parseProposal(value:unknown, projectId:string):RevisionProposal {
  if(!isRecord(value)||typeof value.id!=="string"||!isProjectId(value.id)||value.draft_id!==projectId||
    typeof value.base_job_id!=="string"||!isProjectId(value.base_job_id)||typeof value.base_artifact_id!=="string"||!isProjectId(value.base_artifact_id)||
    !Number.isSafeInteger(value.base_revision)||Number(value.base_revision)<1||typeof value.instruction!=="string"||value.instruction.length>1000||
    !["pending","accepted","rejected","stale","failed"].includes(String(value.state))||!["queued","running","succeeded","failed"].includes(String(value.job_status))||
    !indices(value.before)||(value.after!==null&&(!indices(value.after)||!value.after.length||!subset(value.after,value.before)))||
    (value.explanation!==null&&(typeof value.explanation!=="string"||value.explanation.length>1200))||
    !Array.isArray(value.reasons)||value.reasons.length>12||value.reasons.some(r=>!isRecord(r)||!Number.isSafeInteger(r.window_index)||typeof r.reason!=="string"||r.reason.length>500)||
    !isRecord(value.changes)||!indices(value.changes.removed)||typeof value.changes.reordered!=="boolean"||
    (value.applied_revision!==null&&(!Number.isSafeInteger(value.applied_revision)||Number(value.applied_revision)<1)))return invalid();
  return {id:value.id,draft_id:projectId,base_revision:Number(value.base_revision),base_job_id:value.base_job_id,base_artifact_id:value.base_artifact_id,
    instruction:value.instruction,state:value.state as ProposalState,job_status:value.job_status as AIJobStatus,error_code:typeof value.error_code==="string"?value.error_code:null,
    before:value.before,after:value.after,explanation:value.explanation,reasons:value.reasons,changes:{removed:value.changes.removed,reordered:value.changes.reordered},
    applied_revision:value.applied_revision as number|null,progress:value.job_status==="running"?parseJobProgress(value.progress):null};
}
export async function listProposals(projectId:string,signal?:AbortSignal):Promise<RevisionProposal[]> {
  const value=await requestJSON(path(projectId),{signal});
  if(!isRecord(value)||!Array.isArray(value.items))return invalid();
  return value.items.map(item=>parseProposal(item,projectId));
}
export async function requestRevision(projectId:string,body:{request_id:string;draft_revision:number;instruction:string}):Promise<string> {
  const value=await requestJSON(path(projectId),{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify(body)});
  if(!isRecord(value)||typeof value.id!=="string"||!isProjectId(value.id))return invalid();
  return value.id;
}
export async function decideProposal(projectId:string,id:string,revision:number|null):Promise<{proposal:RevisionProposal;draft:SavedDraft|null}> {
  const value=await requestJSON(`${path(projectId)}/${requireUUID(id,"proposal")}/${revision===null?"reject":"accept"}`,{method:"POST",headers:{"Content-Type":"application/json"},...(revision===null?{}:{body:JSON.stringify({expected_revision:revision})})});
  if(!isRecord(value))return invalid();
  return {proposal:parseProposal(value.proposal,projectId),draft:value.draft===null?null:parseSavedDraft(value.draft)};
}
