import { isProjectId } from "@/lib/api/transport";

/** Persist the session's active job so a refresh can restore it via GET. */
export function writeSavedJobId(
  projectId: string,
  storage: Pick<Storage, "setItem">,
  jobId: string,
): void {
  if (!isProjectId(projectId) || !isProjectId(jobId)) return;
  try {
    storage.setItem(`intentcut:ai-job:${projectId}`, jobId);
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
    const savedId = storage.getItem(`intentcut:ai-job:${projectId}`);
    return savedId && isProjectId(savedId) ? savedId : null;
  } catch {
    return null;
  }
}
