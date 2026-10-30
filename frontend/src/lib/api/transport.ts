/** Shared HTTP transport. Keep project/media/AI behavior in their domain modules. */
export class ApiError extends Error {
  status: number;
  code: string;
  fileIndex?: number;

  constructor(
    message: string,
    status = 0,
    code = "network_error",
    fileIndex?: number,
  ) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.code = code;
    this.fileIndex = fileIndex;
  }
}

export function isProjectId(id: string): boolean {
  return /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i.test(id);
}

export function requireUUID(id: string, kind: string): string {
  if (!isProjectId(id)) {
    throw new ApiError(`Invalid ${kind} ID.`, 0, `invalid_${kind}`);
  }
  return id;
}

export function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function baseUrl(): string {
  const raw = process.env.NEXT_PUBLIC_API_BASE_URL;
  if (!raw) {
    throw new ApiError(
      "Set NEXT_PUBLIC_API_BASE_URL to your local IntentCut API.",
      0,
      "configuration_error",
    );
  }

  let url: URL;
  try {
    url = new URL(raw);
  } catch {
    throw new ApiError("Invalid IntentCut API URL.", 0, "configuration_error");
  }

  // Matches the existing M3.2 local-only contract. Production transport requires
  // a separate security review (identity, project authorization, HTTPS, AI budgets).
  if (
    url.protocol !== "http:" ||
    !["127.0.0.1", "localhost", "[::1]"].includes(url.hostname) ||
    url.username ||
    url.password ||
    url.pathname !== "/" ||
    url.search ||
    url.hash
  ) {
    throw new ApiError(
      "The API URL must be a loopback HTTP origin.",
      0,
      "configuration_error",
    );
  }
  return url.origin;
}

async function apiFetch(path: string, options: RequestInit = {}): Promise<Response> {
  if (!path.startsWith("/") || path.startsWith("//")) {
    throw new ApiError("Invalid API path.", 0, "invalid_request");
  }

  const url = baseUrl() + path;
  let response: Response;
  try {
    response = await fetch(url, {
      ...options,
      credentials: "omit",
      cache: "no-store",
      redirect: "error",
    });
  } catch (error) {
    if (
      options.signal?.aborted ||
      (error instanceof Error && error.name === "AbortError")
    ) {
      throw new ApiError(
        "Request cancelled. A submitted operation may still finish on the server.",
        0,
        "cancelled",
      );
    }
    throw new ApiError(
      "Could not reach the API. A submitted operation may have completed; check before resubmitting.",
      0,
      "network_error",
    );
  }

  if (options.signal?.aborted) {
    throw new ApiError(
      "Request cancelled. Server work may still finish.",
      0,
      "cancelled",
    );
  }
  if (!response.ok) {
    let value: unknown;
    try {
      value = await response.json();
    } catch {
      value = null;
    }
    const body = isRecord(value) ? value : null;
    throw new ApiError(
      typeof body?.message === "string"
        ? body.message
        : `Request failed (${response.status}).`,
      response.status,
      typeof body?.code === "string" ? body.code : "http_error",
      typeof body?.file_index === "number" ? body.file_index : undefined,
    );
  }
  return response;
}

/** Return unknown rather than asserting the remote response matches a TS interface. */
export async function requestJSON(path: string, options: RequestInit = {}): Promise<unknown> {
  const response = await apiFetch(path, options);
  let value: unknown;
  try {
    value = await response.json();
  } catch {
    throw new ApiError("The API returned invalid JSON.", 0, "invalid_response");
  }
  if (options.signal?.aborted) {
    throw new ApiError("Request cancelled. Server work may still finish.", 0, "cancelled");
  }
  if (value === null || typeof value !== "object") {
    throw new ApiError("The API returned an invalid response.", 0, "invalid_response");
  }
  return value;
}

/** For artifact playback/download only. Blob lifecycle belongs to the UI. */
export async function requestBlob(path: string, options: RequestInit = {}): Promise<Blob> {
  const response = await apiFetch(path, options);
  const blob = await response.blob();
  if (options.signal?.aborted) {
    throw new ApiError("Request cancelled.", 0, "cancelled");
  }
  return blob;
}
