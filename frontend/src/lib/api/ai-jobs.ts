import type { AIJob, AIJobAccepted, FirstCutRequest } from "./contracts.ts";
import {
  ApiError,
  canonicalId,
  isProjectId,
  isRecord,
  requestJSON,
  requireUUID,
} from "./transport";
import { isTimestamp, parseJobProgress } from "./job-progress";

export function aiJobsPath(projectId: string): string {
  return `/projects/${requireUUID(projectId, "project")}/ai-jobs`;
}

function validateFirstCut(payload: FirstCutRequest): FirstCutRequest {
  if (payload.kind !== "first_cut") {
    throw new ApiError("Unsupported AI job kind.", 0, "invalid_request");
  }
  const intent = payload.intent.trim();
  if ([...intent].length < 1 || [...intent].length > 1000) {
    throw new ApiError(
      "Your story idea needs 1–1000 characters.",
      0,
      "invalid_intent",
    );
  }
  if (
    !Number.isFinite(payload.target_seconds) ||
    payload.target_seconds <= 0 ||
    payload.target_seconds > 120
  ) {
    throw new ApiError(
      "Length must be more than 0 and at most 120 seconds.",
      0,
      "invalid_duration",
    );
  }
  if (
    !Array.isArray(payload.media_ids) ||
    payload.media_ids.length < 1 ||
    payload.media_ids.length > 10 ||
    payload.media_ids.some((id) => !isProjectId(id)) ||
    new Set(payload.media_ids).size !== payload.media_ids.length
  ) {
    throw new ApiError("Pick 1–10 different saved videos.", 0, "invalid_media");
  }
  return {
    kind: "first_cut",
    intent,
    target_seconds: payload.target_seconds,
    media_ids: payload.media_ids,
  };
}

export async function createAIJob(
  projectId: string,
  payload: FirstCutRequest,
  signal?: AbortSignal,
): Promise<AIJobAccepted> {
  const path = aiJobsPath(projectId);
  const body = JSON.stringify(validateFirstCut(payload));
  const value = await requestJSON(path, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body,
    signal,
  });
  if (
    !isRecord(value) ||
    typeof value.id !== "string" ||
    !isProjectId(value.id) ||
    value.status !== "queued" ||
    value.status_url !== `${path}/${canonicalId(value.id)}`
  ) {
    throw new ApiError(
      "Invalid job confirmation. Check existing jobs before resubmitting.",
      0,
      "invalid_response",
    );
  }
  return value as unknown as AIJobAccepted;
}

function parseAIJob(value: unknown, expectedId?: string): AIJob {
  if (
    !isRecord(value) ||
    typeof value.id !== "string" ||
    !isProjectId(value.id) ||
    (expectedId !== undefined &&
      canonicalId(value.id) !== canonicalId(expectedId)) ||
    typeof value.status !== "string" ||
    !["queued", "running", "succeeded", "failed"].includes(value.status) ||
    !isTimestamp(value.created_at) ||
    !isTimestamp(value.updated_at) ||
    !(value.started_at === null || isTimestamp(value.started_at)) ||
    !(value.finished_at === null || isTimestamp(value.finished_at)) ||
    typeof value.attempt_count !== "number" ||
    !Number.isSafeInteger(value.attempt_count) ||
    Number(value.attempt_count) < 0 ||
    !(value.error_code === null || typeof value.error_code === "string")
  ) {
    throw new ApiError(
      "Invalid AI job status response.",
      0,
      "invalid_response",
    );
  }
  if (
    value.pipeline_version !== undefined &&
    value.pipeline_version !== null &&
    value.pipeline_version !== "uploaded_v1" &&
    value.pipeline_version !== "highlight_v1"
  ) {
    throw new ApiError(
      "Invalid AI job pipeline.",
      0,
      "invalid_response",
    );
}
  const progress = parseJobProgress(value.progress);
  return {
    ...(value as unknown as AIJob),
    progress: value.status === "running" ? progress : null,
  };
}

export async function getAIJob(
  projectId: string,
  jobId: string,
  signal?: AbortSignal,
): Promise<AIJob> {
  const path = `${aiJobsPath(projectId)}/${requireUUID(jobId, "job")}`;
  const value = await requestJSON(path, { signal });
  return parseAIJob(value, jobId);
}

/** Existing first-cut/highlight jobs, newest first. Recovery reads only. */
export async function listAIJobs(
  projectId: string,
  signal?: AbortSignal,
): Promise<AIJob[]> {
  const value = await requestJSON(aiJobsPath(projectId), { signal });
  if (!isRecord(value) || !Array.isArray(value.items)) {
    throw new ApiError("Invalid AI job list response.", 0, "invalid_response");
  }
  return value.items.map((item) => parseAIJob(item));
}
