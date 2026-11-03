import type { AIJobAccepted } from "./contracts.ts";
import {
  ApiError,
  isProjectId,
  isRecord,
  requestJSON,
  requireUUID,
} from "./transport";

export interface HighlightCandidate {
  id: string;
  media_id: string;
  start_seconds: number;
  end_seconds: number;
  score: number;
  components: Record<string, number>;
  heuristic_only: true;
}

export interface HighlightCandidateList {
  media_id: string;
  duration_seconds: number;
  sha256: string;
  candidates: HighlightCandidate[];
}

export interface HighlightJobRequest {
  kind: "highlight";
  intent: string;
  target_seconds: number;
  media_ids: [string];
  candidate_seconds?: number;
  max_candidates?: number;
  candidate_ids?: string[];
}

export function highlightsPath(projectId: string): string {
  return `/projects/${requireUUID(projectId, "project")}/ai-jobs/highlights`;
}

function isCandidate(value: unknown): value is HighlightCandidate {
  if (!isRecord(value)) return false;
  const v = value as Record<string, unknown>;
  return (
    typeof v.id === "string" &&
    typeof v.media_id === "string" &&
    typeof v.start_seconds === "number" &&
    typeof v.end_seconds === "number" &&
    Number.isFinite(v.start_seconds) &&
    Number.isFinite(v.end_seconds) &&
    v.start_seconds >= 0 &&
    v.end_seconds > v.start_seconds &&
    typeof v.score === "number" &&
    Number.isFinite(v.score) &&
    isRecord(v.components) &&
    v.heuristic_only === true
  );
}

export function parseCandidateList(value: unknown): HighlightCandidateList {
  if (!isRecord(value)) {
    throw new ApiError("The API returned an invalid response.", 0, "invalid_response");
  }
  const v = value as Record<string, unknown>;
  if (
    typeof v.media_id !== "string" ||
    !isProjectId(v.media_id) ||
    typeof v.duration_seconds !== "number" ||
    !Number.isFinite(v.duration_seconds) ||
    v.duration_seconds <= 0 ||
    typeof v.sha256 !== "string" ||
    !Array.isArray(v.candidates) ||
    v.candidates.length > 12 ||
    !v.candidates.every(isCandidate)
  ) {
    throw new ApiError("The API returned an invalid response.", 0, "invalid_response");
  }
  return value as unknown as HighlightCandidateList;
}

export async function listHighlightCandidates(
  projectId: string,
  mediaId: string,
  options: { candidate_seconds?: number; max_candidates?: number } = {},
  signal?: AbortSignal,
): Promise<HighlightCandidateList> {
  requireUUID(mediaId, "media");
  const params = new URLSearchParams({ media_id: mediaId });
  if (options.candidate_seconds !== undefined) {
    params.set("candidate_seconds", String(options.candidate_seconds));
  }
  if (options.max_candidates !== undefined) {
    params.set("max_candidates", String(options.max_candidates));
  }
  const value = await requestJSON(`${highlightsPath(projectId)}/candidates?${params}`, { signal });
  return parseCandidateList(value);
}

export function highlightPreviewUrl(
  projectId: string,
  mediaId: string,
  startSeconds: number,
  endSeconds: number,
): string {
  const base = process.env.NEXT_PUBLIC_API_BASE_URL;
  if (!base) {
    throw new ApiError(
      "Set NEXT_PUBLIC_API_BASE_URL to your local IntentCut API.",
      0,
      "configuration_error",
    );
  }
  const params = new URLSearchParams({
    media_id: requireUUID(mediaId, "media"),
    start_seconds: String(startSeconds),
    end_seconds: String(endSeconds),
  });
  return `${base.replace(/\/$/, "")}${highlightsPath(projectId)}/preview?${params}`;
}

function validateHighlightJob(payload: HighlightJobRequest): HighlightJobRequest {
  if (payload.kind !== "highlight") {
    throw new ApiError("Unsupported AI job kind.", 0, "invalid_request");
  }
  const intent = payload.intent.trim();
  if ([...intent].length < 1 || [...intent].length > 1000) {
    throw new ApiError("Your story idea needs 1–1000 characters.", 0, "invalid_intent");
  }
  if (!Number.isFinite(payload.target_seconds) || payload.target_seconds <= 0 || payload.target_seconds > 120) {
    throw new ApiError(
      "Length must be more than 0 and at most 120 seconds.",
      0,
      "invalid_duration",
    );
  }
  if (!Array.isArray(payload.media_ids) || payload.media_ids.length !== 1 || !isProjectId(payload.media_ids[0])) {
    throw new ApiError("Pick one long video.", 0, "invalid_media");
  }
  if (
    payload.candidate_ids !== undefined &&
    (!Array.isArray(payload.candidate_ids) ||
      payload.candidate_ids.length < 1 ||
      payload.candidate_ids.length > 12 ||
      payload.candidate_ids.some((id) => !/^hl-\d{2}$/.test(id)) ||
      new Set(payload.candidate_ids).size !== payload.candidate_ids.length)
  ) {
    throw new ApiError("Your moment picks look off. Pick again.", 0, "invalid_candidates");
  }
  return {
    kind: "highlight",
    intent,
    target_seconds: payload.target_seconds,
    media_ids: [payload.media_ids[0]],
    ...(payload.candidate_seconds !== undefined ? { candidate_seconds: payload.candidate_seconds } : {}),
    ...(payload.max_candidates !== undefined ? { max_candidates: payload.max_candidates } : {}),
    ...(payload.candidate_ids !== undefined ? { candidate_ids: payload.candidate_ids } : {}),
  };
}

function parseAccepted(value: unknown): AIJobAccepted {
  if (
    !isRecord(value) ||
    typeof value.id !== "string" ||
    !isProjectId(value.id) ||
    typeof value.status_url !== "string"
  ) {
    throw new ApiError("The API returned an invalid response.", 0, "invalid_response");
  }
  return value as unknown as AIJobAccepted;
}

export async function createHighlightJob(
  projectId: string,
  payload: HighlightJobRequest,
  signal?: AbortSignal,
): Promise<AIJobAccepted> {
  const body = validateHighlightJob(payload);
  const value = await requestJSON(highlightsPath(projectId), {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
    signal,
  });
  return parseAccepted(value);
}
