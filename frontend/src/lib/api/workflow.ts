import { requireUUID } from "./transport";
export type EditingWorkflow = "first_cut" | "highlights";
export const workflowScope = (projectId: string, workflow: EditingWorkflow) => workflow === "first_cut" ? projectId : `${projectId}:highlights`;
export function editingPath(projectId: string, suffix = "", workflow: EditingWorkflow = "first_cut") {
  return `/projects/${requireUUID(projectId, "project")}/edit-draft${suffix}${workflow === "highlights" ? "?workflow=highlights" : ""}`;
}
