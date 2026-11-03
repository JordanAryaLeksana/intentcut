import type { Project } from "./contracts";
import {
  ApiError,
  canonicalId,
  isProjectId,
  isRecord,
  requestJSON,
  requireUUID,
} from "./transport";

const SLUG_PATTERN = /^[a-z0-9]+(?:-[a-z0-9]+)*$/;

export function isProjectSlug(value: string): boolean {
  return value.length >= 1 && value.length <= 80 && SLUG_PATTERN.test(value);
}

/** Canonical Studio URL for a project: readable slug when available. */
export function projectStudioPath(project: {
  id: string;
  slug: string | null;
}): string {
  return project.slug
    ? `/studio/${project.slug}`
    : `/projects/${canonicalId(project.id)}`;
}

/**
 * A UUID arriving under /studio/ is a legacy link. Send it to the
 * legacy route, which redirects once to the readable URL; anything
 * else is treated as a slug (or rejected as not found downstream).
 */
export function legacyRedirectForStudioSlug(slug: string): string | null {
  return isProjectId(slug) ? `/projects/${canonicalId(slug)}` : null;
}

function parseProject(value: unknown): Project {
  if (
    !isRecord(value) ||
    typeof value.id !== "string" ||
    !isProjectId(value.id) ||
    typeof value.name !== "string" ||
    !(value.slug === null || value.slug === undefined || typeof value.slug === "string") ||
    (typeof value.slug === "string" && !isProjectSlug(value.slug)) ||
    typeof value.created_at !== "string"
  ) {
    throw new ApiError(
      "Invalid project response. Check the backend before creating another project.",
      0,
      "invalid_response",
    );
  }
  return {
    id: canonicalId(value.id),
    name: value.name,
    slug: typeof value.slug === "string" ? value.slug : null,
    created_at: value.created_at,
  };
}

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
  return parseProject(value);
}

/** Reopen check: the persisted project row, or a definitive 404. */
export async function getProject(
  projectId: string,
  signal?: AbortSignal,
): Promise<Project> {
  const id = requireUUID(projectId, "project");
  const project = parseProject(
    await requestJSON(`/projects/${id}`, { signal }),
  );
  if (project.id !== id) {
    throw new ApiError(
      "Invalid project response. Check the backend before continuing.",
      0,
      "invalid_response",
    );
  }
  return project;
}

/** Resolve a readable Studio URL to its project at the app boundary. */
export async function getProjectBySlug(
  slug: string,
  signal?: AbortSignal,
): Promise<Project> {
  if (!isProjectSlug(slug)) {
    throw new ApiError("That project link is not valid.", 0, "invalid_slug");
  }
  return parseProject(
    await requestJSON(`/projects/by-slug/${slug}`, { signal }),
  );
}

/** Project library: every persisted project, newest first. */
export async function listProjects(
  signal?: AbortSignal,
): Promise<Project[]> {
  const value = await requestJSON("/projects", { signal });
  if (!isRecord(value) || !Array.isArray(value.items)) {
    throw new ApiError(
      "Invalid project list response. Check the backend before continuing.",
      0,
      "invalid_response",
    );
  }
  return value.items.map((item) => parseProject(item));
}
