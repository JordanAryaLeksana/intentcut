import type {
  MediaAsset,
  MediaList,
  MediaUploadResponse,
} from "./contracts";

import {
  ApiError,
  isProjectId,
  isRecord,
  requestJSON,
  requireUUID,
} from "./transport";

const PAGE_SIZE = 100;
const MAX_FILES = 10;
const MAX_FILE_BYTES = 128 * 1024 ** 2;
// Preserve the deliberately conservative UI cap from M3.2 (backend allows 512 MiB).
const MAX_REQUEST_BYTES = 500 * 1024 ** 2;

function mediaPath(projectId: string): string {
  return `/projects/${requireUUID(projectId, "project")}/media`;
}

function isMediaAsset(value: unknown, projectId: string): value is MediaAsset {
  return (
    isRecord(value) &&
    typeof value.id === "string" &&
    isProjectId(value.id) &&
    value.project_id === projectId &&
    typeof value.original_filename === "string" &&
    typeof value.size_bytes === "number" &&
    Number.isFinite(value.size_bytes) &&
    value.size_bytes >= 0 &&
    typeof value.duration_seconds === "number" &&
    Number.isFinite(value.duration_seconds) &&
    value.duration_seconds >= 0 &&
    typeof value.created_at === "string" &&
    isRecord(value.video) &&
    (value.audio === null || isRecord(value.audio))
  );
}

export async function listMedia(
  id: string,
  signal?: AbortSignal,
  offset = 0,
): Promise<MediaList> {
  if (!Number.isSafeInteger(offset) || offset < 0) {
    throw new ApiError("Invalid media offset.", 0, "invalid_offset");
  }
  const value = await requestJSON(
    `${mediaPath(id)}?limit=${PAGE_SIZE}&offset=${offset}`,
    {
      signal,
    },
  );
  if (
    !isRecord(value) ||
    !Array.isArray(value.items) ||
    value.items.length > PAGE_SIZE ||
    value.items.some((item: unknown) => !isMediaAsset(item, id)) ||
    value.limit !== PAGE_SIZE ||
    value.offset !== offset
  ) {
    throw new ApiError("Invalid media list response.", 0, "invalid_response");
  }
  return value as unknown as MediaList;
}

export async function listAllMedia(
  id: string,
  signal?: AbortSignal,
): Promise<MediaAsset[]> {
  const items: MediaAsset[] = [];
  for (let offset = 0; ; offset += PAGE_SIZE) {
    const page = await listMedia(id, signal, offset);
    items.push(...page.items);
    if (page.items.length < PAGE_SIZE) return items;
  }
}

export async function getMedia(
  projectId: string,
  mediaId: string,
  signal?: AbortSignal,
): Promise<MediaAsset> {
  const id = requireUUID(mediaId, "media");
  const value = await requestJSON(`${mediaPath(projectId)}/${id}`, { signal });
  if (!isMediaAsset(value, projectId) || value.id !== id) {
    throw new ApiError("Invalid media response.", 0, "invalid_response");
  }
  return value;
}

export async function uploadMedia(
  id: string,
  files: File[],
  signal?: AbortSignal,
): Promise<MediaUploadResponse> {
  if (
    files.length < 1 ||
    files.length > MAX_FILES ||
    files.some((file) => file.size > MAX_FILE_BYTES) ||
    files.reduce((sum, file) => sum + file.size, 0) > MAX_REQUEST_BYTES
  ) {
    throw new ApiError(
      "Upload 1–10 videos, up to 128 MiB each and 500 MiB total.",
      0,
      "upload_limit",
    );
  }
  const body = new FormData();
  files.forEach((file) => body.append("files", file));
  // Never manually set Content-Type: the browser must supply the multipart boundary.
  // Cancellation does not imply server rollback. Never automatically retry.
  const value = await requestJSON(mediaPath(id), {
    method: "POST",
    body,
    signal,
  });
  if (
    !isRecord(value) ||
    !Array.isArray(value.items) ||
    value.items.length !== files.length ||
    value.items.some((item: unknown) => !isMediaAsset(item, id))
  ) {
    throw new ApiError(
      "Invalid upload confirmation. Refresh saved media before resubmitting.",
      0,
      "invalid_response",
    );
  }
  return value as unknown as MediaUploadResponse;
}
