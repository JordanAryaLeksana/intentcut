import type { Project } from "./contracts";
import { ApiError, isProjectId, isRecord, requestJSON } from "./transport";

export async function createProject(name: string, signal?: AbortSignal): Promise<Project> {
  const trimmed = name.trim();
  if (!trimmed || [...trimmed].length > 200) {
    throw new ApiError("Use a project name between 1 and 200 characters.", 0, "invalid_name");
  }
  const value = await requestJSON("/projects", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ name: trimmed }),
    signal,
  });
  if (
    !isRecord(value) ||
    typeof value.id !== "string" ||
    !isProjectId(value.id) ||
    typeof value.name !== "string" ||
    typeof value.created_at !== "string"
  ) {
    throw new ApiError(
      "Invalid project response. Check the backend before creating another project.",
      0,
      "invalid_response",
    );
  }
  return value as unknown as Project;
}
