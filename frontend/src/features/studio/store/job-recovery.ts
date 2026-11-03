import { canonicalId, isProjectId } from "@/lib/api/transport";
import type { AIJob } from "@/lib/api/contracts";

/** Persist the session's active job so a refresh can restore it via GET. */
export function writeSavedJobId(
  projectId: string,
  storage: Pick<Storage, "setItem">,
  jobId: string,
): void {
  if (!isProjectId(projectId) || !isProjectId(jobId)) return;
  try {
    storage.setItem(
      `intentcut:ai-job:${canonicalId(projectId)}`,
      canonicalId(jobId),
    );
  } catch {
    // Storage is optional; the in-memory active job still applies.
  }
}

/** Recovery only restores an identifier; status and ownership are checked by GET. */
export function readSavedJobId(
  projectId: string,
  storage: Pick<Storage, "getItem">,
): string | null {
  if (!isProjectId(projectId)) return null;
  try {
    const savedId = storage.getItem(`intentcut:ai-job:${canonicalId(projectId)}`);
    return savedId && isProjectId(savedId) ? canonicalId(savedId) : null;
  } catch {
    return null;
  }
}

/** Forget a job the server definitively rejects (404), never on transient errors. */
export function removeSavedJobId(
  projectId: string,
  storage: Pick<Storage, "removeItem">,
): void {
  if (!isProjectId(projectId)) return;
  try {
    storage.removeItem(`intentcut:ai-job:${canonicalId(projectId)}`);
  } catch {
    // Storage is optional; the in-memory clear still applies.
  }
}

/** Newest server job Studio may adopt on reopen; failed jobs stay submittable. */
export function latestRecoverableJobId(jobs: AIJob[]): string | null {
  const job = jobs.find((item) => item.status !== "failed");
  return job ? canonicalId(job.id) : null;
}
