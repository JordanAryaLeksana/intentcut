/** Identity-only edits: the backend resolves all ranges and media paths. */
import { ApiError, isProjectId, isRecord, requestJSON, requireUUID } from "./transport";
import { parsePublicStoryboard, type PublicStoryboard } from "@/features/studio/ai-director/storyboard/storyboard-schema";
import type { AIJobStatus } from "./contracts";

export interface SavedDraft {
  revision: number;
  base_job_id: string;
  base_artifact_id: string;
  window_indices: number[];
  updated_at: string;
  storyboard: PublicStoryboard;
}
export interface RenderVersion { job_id: string; revision: number; status: AIJobStatus }
const path = (projectId: string) => `/projects/${requireUUID(projectId, "project")}/edit-draft`;
function invalid(): never { throw new ApiError("Invalid editing response.", 0, "invalid_response"); }
export function parseSavedDraft(value: unknown): SavedDraft {
  if (!isRecord(value) || !Number.isSafeInteger(value.revision) || Number(value.revision) < 1 ||
      typeof value.base_job_id !== "string" || !isProjectId(value.base_job_id) ||
      typeof value.base_artifact_id !== "string" || !isProjectId(value.base_artifact_id) ||
      typeof value.updated_at !== "string" || !Number.isFinite(Date.parse(value.updated_at)) ||
      !Array.isArray(value.window_indices) || value.window_indices.length > 12 ||
      value.window_indices.some(i => !Number.isSafeInteger(i) || i < 0) ||
      new Set(value.window_indices).size !== value.window_indices.length) return invalid();
  const storyboard = parsePublicStoryboard(value.storyboard);
  const allowed = new Set(storyboard.cuts.map(c => c.window_index));
  if (value.window_indices.some(i => !allowed.has(i))) return invalid();
  return { revision: Number(value.revision), base_job_id: value.base_job_id, base_artifact_id: value.base_artifact_id,
    updated_at: value.updated_at, window_indices: value.window_indices, storyboard };
}
export async function getSavedDraft(projectId: string, signal?: AbortSignal): Promise<SavedDraft | null> {
  const value = await requestJSON(path(projectId), { signal });
  if (!isRecord(value)) return invalid();
  return value.draft === null ? null : parseSavedDraft(value.draft);
}
export async function saveDraft(projectId: string, body: {expected_revision: number; base_job_id: string; base_artifact_id: string; window_indices: number[]}): Promise<SavedDraft> {
  return parseSavedDraft(await requestJSON(path(projectId), {method:"PUT", headers:{"Content-Type":"application/json"}, body:JSON.stringify(body)}));
}
export async function listRenderVersions(projectId: string, signal?: AbortSignal): Promise<RenderVersion[]> {
  const value = await requestJSON(`${path(projectId)}/renders`, { signal });
  if (!isRecord(value) || !Array.isArray(value.items)) return invalid();
  return value.items.map((item: unknown) => {
    if (!isRecord(item) || typeof item.job_id !== "string" || !isProjectId(item.job_id) ||
        !Number.isSafeInteger(item.revision) || Number(item.revision)<1 ||
        !["queued","running","succeeded","failed"].includes(String(item.status))) return invalid();
    return {job_id:item.job_id, revision:Number(item.revision), status:item.status as AIJobStatus};
  });
}
export async function renderDraft(projectId: string, revision: number): Promise<string> {
  const value = await requestJSON(`${path(projectId)}/renders`, {method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({revision})});
  if (!isRecord(value) || typeof value.id !== "string" || !isProjectId(value.id)) return invalid();
  return value.id;
}
