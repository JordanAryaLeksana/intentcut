import type { AIJob, FirstCutRequest } from "@/lib/api/contracts";
import { canonicalId, isProjectId, isRecord } from "@/lib/api/transport";

export function isProcessing(job?: AIJob): boolean {
  return job?.status === "queued" || job?.status === "running";
}

/** The server list is newest first. In-flight work takes precedence over history. */
export function recoveryJob(jobs: AIJob[]): AIJob | undefined {
  const firstCutJobs = jobs.filter(
    (job) => job.pipeline_version === "uploaded_v1"
  );

  return firstCutJobs.find(isProcessing) ?? firstCutJobs[0];
}
export function validFirstCutRequest(value: unknown): value is FirstCutRequest {
  return (
    isRecord(value) &&
    value.kind === "first_cut" &&
    typeof value.intent === "string" &&
    [...value.intent.trim()].length > 0 &&
    [...value.intent.trim()].length <= 1000 &&
    typeof value.target_seconds === "number" &&
    Number.isFinite(value.target_seconds) &&
    value.target_seconds > 0 &&
    value.target_seconds <= 120 &&
    Array.isArray(value.media_ids) &&
    value.media_ids.length > 0 &&
    value.media_ids.length <= 10 &&
    value.media_ids.every((id) => typeof id === "string" && isProjectId(id)) &&
    new Set(value.media_ids).size === value.media_ids.length
  );
}

const requestKey = (projectId: string, jobId: string) =>
  `intentcut:first-cut-inputs:${canonicalId(projectId)}:${canonicalId(jobId)}`;

export function readFirstCutRequest(
  projectId: string,
  jobId: string,
): FirstCutRequest | null {
  try {
    const value: unknown = JSON.parse(
      window.sessionStorage.getItem(requestKey(projectId, jobId)) ?? "null",
    );
    return validFirstCutRequest(value) ? value : null;
  } catch {
    return null;
  }
}

export function saveFirstCutRequest(
  projectId: string,
  jobId: string,
  request: FirstCutRequest,
): void {
  try {
    window.sessionStorage.setItem(
      requestKey(projectId, jobId),
      JSON.stringify(request),
    );
  } catch {
    /* Optional storage: server recovery still works, with manual input editing. */
  }
}
