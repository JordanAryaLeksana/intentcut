import { aiJobsPath } from "./ai-jobs";
import { ApiError, isRecord, isProjectId, requireUUID, requestJSON } from "./transport";

export interface CueEdit { index: number; text: string; enabled: boolean }
export interface CaptionCue extends CueEdit { start_ms: number; end_ms: number }
export interface CaptionSet {
  id: string; project_id: string; parent_artifact_id: string; parent_sha256: string;
  transcription_sha256: string; revision: number; duration_ms: number;
  cues: CaptionCue[]; updated_at: string;
}
export interface CaptionJob {
  id: string; status: "queued" | "running" | "succeeded" | "failed";
  error_code: string | null; kind: "caption_transcribe_v1" | "caption_burn_v1";
  caption_set_id: string | null; caption_revision: number | null; enabled_cues?: number | null;
}
export interface VideoCaptions {
  video_artifact_id: string; parent_sha256: string; sets: CaptionSet[];
  transcriptions: {id: string; job_id: string}[]; jobs: CaptionJob[];
}
function invalid(): never { throw new ApiError("Invalid caption response.", 0, "invalid_response"); }
const hash = (value: unknown): value is string => typeof value === "string" && /^[0-9a-f]{64}$/.test(value);
const uuid = (value: unknown): value is string => typeof value === "string" && isProjectId(value);
const integer = (value: unknown): value is number => typeof value === "number" && Number.isSafeInteger(value);
export function parseCaptionSet(value: unknown, project: string, video?: string): CaptionSet {
  if (!isRecord(value) || !uuid(value.id) || value.project_id !== project || !uuid(value.parent_artifact_id)
    || (video && value.parent_artifact_id !== video) || !hash(value.parent_sha256) || !hash(value.transcription_sha256)
    || !integer(value.revision) || value.revision < 1 || !integer(value.duration_ms) || value.duration_ms <= 0
    || typeof value.updated_at !== "string" || !Number.isFinite(Date.parse(value.updated_at)) || !Array.isArray(value.cues) || value.cues.length > 5000) return invalid();
  let previous = -1;
  const duration = value.duration_ms;
  const cues = value.cues.map((cue: unknown, index): CaptionCue => {
    if (!isRecord(cue) || cue.index !== index || !integer(cue.start_ms) || !integer(cue.end_ms)
      || cue.start_ms < previous || cue.start_ms < 0 || cue.end_ms <= cue.start_ms || cue.end_ms > duration
      || typeof cue.text !== "string" || cue.text.length > 2000 || typeof cue.enabled !== "boolean"
      || (cue.enabled && !cue.text.trim())) return invalid();
    previous = cue.start_ms;
    return {index, start_ms: cue.start_ms, end_ms: cue.end_ms, text: cue.text, enabled: cue.enabled};
  });
  return {id: value.id, project_id: project, parent_artifact_id: value.parent_artifact_id,
    parent_sha256: value.parent_sha256, transcription_sha256: value.transcription_sha256,
    revision: value.revision, duration_ms: duration, cues, updated_at: value.updated_at};
}
export async function getVideoCaptions(project: string, video: string, signal?: AbortSignal): Promise<VideoCaptions> {
  const value = await requestJSON(`${aiJobsPath(project)}/videos/${requireUUID(video, "video")}/captions`, {signal});
  if (!isRecord(value) || value.video_artifact_id !== video || !hash(value.parent_sha256)
    || !Array.isArray(value.sets) || !Array.isArray(value.transcriptions) || !Array.isArray(value.jobs)) return invalid();
  const sets = value.sets.map((v: unknown) => parseCaptionSet(v, project, video));
  if (sets.some(s => s.parent_sha256 !== value.parent_sha256)) return invalid();
  const transcriptions = value.transcriptions.map((t: unknown) => {
    if (!isRecord(t) || !uuid(t.id) || !uuid(t.job_id)) return invalid();
    return {id: t.id, job_id: t.job_id};
  });
  const jobs = value.jobs.map((j: unknown): CaptionJob => {
    if (!isRecord(j) || !uuid(j.id) || !["queued","running","succeeded","failed"].includes(String(j.status))
      || !["caption_transcribe_v1","caption_burn_v1"].includes(String(j.kind))
      || (j.error_code !== null && typeof j.error_code !== "string")
      || (j.enabled_cues != null && (!integer(j.enabled_cues) || j.enabled_cues < 0))
      || (j.caption_set_id !== null && !uuid(j.caption_set_id))
      || (j.caption_revision !== null && (!integer(j.caption_revision) || j.caption_revision < 1))) return invalid();
    // Explicit branches preserve the narrow public contract.
    const status = j.status;
    const kind = j.kind;
    if ((status !== "queued" && status !== "running" && status !== "succeeded" && status !== "failed")
      || (kind !== "caption_transcribe_v1" && kind !== "caption_burn_v1")) return invalid();
    return {id:j.id, status, kind, enabled_cues:typeof j.enabled_cues === "number" ? j.enabled_cues : null, error_code:typeof j.error_code === "string" ? j.error_code : null,
      caption_set_id:typeof j.caption_set_id === "string" ? j.caption_set_id : null,
      caption_revision:typeof j.caption_revision === "number" ? j.caption_revision : null};
  });
  return {video_artifact_id:video, parent_sha256:value.parent_sha256, sets, transcriptions, jobs};
}
const path = (p: string, id: string) => `${aiJobsPath(p)}/caption-sets/${requireUUID(id,"caption")}`;
export async function createCaptionSet(project: string, artifact: string): Promise<CaptionSet> {
  const value = await requestJSON(`${aiJobsPath(project)}/caption-sets`, {method:"POST", headers:{"Content-Type":"application/json"}, body:JSON.stringify({transcription_artifact_id:requireUUID(artifact,"transcription")})});
  const result=parseCaptionSet(value, project);
  if(result.id!==artifact)return invalid();
  return result;
}
export async function getCaptionSet(project: string, id: string): Promise<CaptionSet> {
  const result=parseCaptionSet(await requestJSON(path(project,id)), project);
  if(result.id!==id)return invalid();
  return result;
}
export async function saveCaptionSet(project: string, id: string, revision: number, cues: CueEdit[]): Promise<CaptionSet> {
  const result=parseCaptionSet(await requestJSON(path(project,id), {method:"PUT",headers:{"Content-Type":"application/json"},body:JSON.stringify({expected_revision:revision,cues})}),project);
  if(result.id!==id)return invalid();
  return result;
}
export async function transcribeVideo(project: string, video: string, requestId: string): Promise<string> {
  const value = await requestJSON(`${aiJobsPath(project)}/transcriptions`,{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({request_id:requireUUID(requestId,"request"),artifact_id:requireUUID(video,"video")})});
  if (!isRecord(value) || !uuid(value.id)) return invalid();
  return value.id;
}
export async function exportCaptions(project: string, id: string, revision: number): Promise<string> {
  const value = await requestJSON(`${path(project,id)}/exports`,{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({expected_revision:revision})});
  if (!isRecord(value) || !uuid(value.id)) return invalid();
  return value.id;
}
