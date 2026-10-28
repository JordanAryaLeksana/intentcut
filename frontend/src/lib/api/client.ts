// Public contracts verified against FastAPI OpenAPI 0.2.0.
export interface Project { id: string; name: string; created_at: string }
export interface MediaAsset {
  id: string; project_id: string; original_filename: string; size_bytes: number;
  duration_seconds: number; created_at: string;
  video: { stream_index: number; codec: string; width: number; height: number; pixel_format: string; frame_rate: { numerator: number; denominator: number } };
  audio: { stream_index: number; codec: string; sample_rate: number; channels: number } | null;
}
export interface MediaList { items: MediaAsset[]; limit: number; offset: number }
export class ApiError extends Error {
  status: number; code: string; fileIndex?: number;
  constructor(message: string, status = 0, code = "network_error", fileIndex?: number) {
    super(message); this.name = "ApiError"; this.status = status; this.code = code; this.fileIndex = fileIndex;
  }
}
export function isProjectId(id: string) { return /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i.test(id); }
function projectPath(id: string) { if (!isProjectId(id)) throw new ApiError("Invalid project ID.", 0, "invalid_project"); return `/projects/${id}/media`; }
function baseUrl() {
  const value = process.env.NEXT_PUBLIC_API_BASE_URL;
  if (!value) throw new ApiError("Set NEXT_PUBLIC_API_BASE_URL to your local IntentCut API.", 0, "configuration_error");
  const url = new URL(value);
  if (url.protocol !== "http:" || !["127.0.0.1", "localhost", "[::1]"].includes(url.hostname) || url.username || url.password || url.pathname !== "/" || url.search || url.hash) throw new ApiError("The API URL must be a loopback HTTP origin.", 0, "configuration_error");
  return url.origin;
}
async function request<T>(path: string, options: RequestInit): Promise<T> {
  const url = baseUrl() + path;
  let response: Response;
  try { response = await fetch(url, { ...options, credentials: "omit", cache: "no-store" }); }
  catch (error) {
    if (options.signal?.aborted || (error instanceof Error && error.name === "AbortError")) throw new ApiError("Request cancelled. A submitted operation may still finish on the server.", 0, "cancelled");
    throw new ApiError("Could not reach the API. Check the server and allowed origin. A submitted operation may have completed; check before resubmitting.");
  }
  const body = await response.json().catch(() => null);
  if (options.signal?.aborted) throw new ApiError("Request cancelled. Server work may still finish.", 0, "cancelled");
  if (!response.ok) throw new ApiError(typeof body?.message === "string" ? body.message : `Request failed (${response.status}).`, response.status, typeof body?.code === "string" ? body.code : "http_error", typeof body?.file_index === "number" ? body.file_index : undefined);
  if (!body || typeof body !== "object") throw new ApiError("The API returned an invalid response. Check before resubmitting.", 0, "invalid_response");
  return body as T;
}
export async function createProject(name: string, signal?: AbortSignal): Promise<Project> {
  const trimmed = name.trim();
  if (!trimmed || [...trimmed].length > 200) throw new ApiError("Use a project name between 1 and 200 characters.", 0, "invalid_name");
  const project = await request<Project>("/projects", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ name: trimmed }), signal });
  if (!isProjectId(project.id) || typeof project.name !== "string") throw new ApiError("Invalid project response. Check the backend before creating another project.", 0, "invalid_response");
  return project;
}
export function listMedia(id: string, signal?: AbortSignal, offset = 0): Promise<MediaList> {
  return request(`${projectPath(id)}?limit=100&offset=${offset}`, { signal });
}
export async function listAllMedia(id: string, signal?: AbortSignal): Promise<MediaAsset[]> {
  const items: MediaAsset[] = [];
  for (let offset = 0; ; offset += 100) { const page = await listMedia(id, signal, offset); if (!Array.isArray(page.items)) throw new ApiError("Invalid media list response.", 0, "invalid_response"); items.push(...page.items); if (page.items.length < 100) return items; }
}
export async function uploadMedia(id: string, files: File[], signal?: AbortSignal): Promise<{items: MediaAsset[]}> {
  if (!files.length || files.length > 10 || files.some(f => f.size > 128 * 1024 ** 2) || files.reduce((sum,f)=>sum+f.size,0) > 500 * 1024 ** 2) throw new ApiError("Upload 1–10 videos, up to 128 MiB each and 500 MiB total.", 0, "upload_limit");
  const body = new FormData(); files.forEach(file => body.append("files", file));
  const result = await request<{items: MediaAsset[]}>(projectPath(id), { method: "POST", body, signal });
  if (!Array.isArray(result.items) || result.items.length !== files.length || result.items.some(item => !isProjectId(item.id) || item.project_id !== id)) throw new ApiError("Invalid upload confirmation. Refresh saved media before resubmitting.", 0, "invalid_response");
  return result;
}
