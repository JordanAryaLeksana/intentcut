import { isProjectId } from "@/lib/api/transport";

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
