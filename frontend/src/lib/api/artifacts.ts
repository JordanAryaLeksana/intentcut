import type { AIArtifactList } from "./contracts.ts";
import { aiJobsPath } from "./ai-jobs";
import { ApiError, isProjectId, isRecord, requestBlob, requestJSON, requireUUID } from "./transport";

function artifactsPath(projectId: string, jobId: string): string {
  return `${aiJobsPath(projectId)}/${requireUUID(jobId, "job")}/artifacts`;
}

export async function listAIArtifacts(
  projectId: string,
  jobId: string,
  signal?: AbortSignal,
): Promise<AIArtifactList> {
  const path = artifactsPath(projectId, jobId);
  const value = await requestJSON(path, { signal });
  if (
    !isRecord(value) ||
    !Array.isArray(value.items) ||
    value.items.some((item: unknown) => {
      if (!isRecord(item)) return true;
      return (
        typeof item.id !== "string" ||
        !isProjectId(item.id) ||
        typeof item.kind !== "string" ||
        !item.kind ||
        (typeof item.size_bytes !== "number" || !Number.isSafeInteger(item.size_bytes)) ||
        Number(item.size_bytes) < 0 ||
        item.download_url !== `${path}/${item.id}`
      );
    })
  ) {
    throw new ApiError("Invalid artifact list response.", 0, "invalid_response");
  }
  return value as unknown as AIArtifactList;
}

/** Fetch by validated identifiers, never by an arbitrary server-supplied URL. */
export function downloadAIArtifact(
  projectId: string,
  jobId: string,
  artifactId: string,
  signal?: AbortSignal,
): Promise<Blob> {
  const path = `${artifactsPath(projectId, jobId)}/${requireUUID(artifactId, "artifact")}`;
  return requestBlob(path, { signal });
}

/** Storyboard JSON is unknown until its actual published schema is inspected. */
export function loadAIArtifactJSON(
  projectId: string,
  jobId: string,
  artifactId: string,
  signal?: AbortSignal,
): Promise<unknown> {
  const path = `${artifactsPath(projectId, jobId)}/${requireUUID(artifactId, "artifact")}`;
  return requestJSON(path, { signal });
}
