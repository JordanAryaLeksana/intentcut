# M2B.8: AI job REST API

**Historical milestone:** M2B.9 supersedes the POST-unavailable behavior below.
See [the current uploaded-media guide](M2B9_UPLOADED_MEDIA.md) for 202 creation,
worker execution, extended public storyboard fields, and processing budgets.
The local-only guard and artifact-download protections described here still apply.

The API reads existing persistent AI jobs and registered artifacts without changing
M2B.7 publication, lease fencing, atomic completion, or uncertain-commit behavior.
HTTP requests never run Muse, FFprobe, FFmpeg, or the processing adapter.

## Access boundary and local setup

There is no user identity, project membership table, authentication, or per-user
authorization in this repository. Project scoping checks record ownership only;
knowing a project UUID does not establish a user's permission. All trusted local
users can inspect every project in this development database.

AI job routes default to **disabled**, returning 503 `ai_api_unavailable`. To inspect
local jobs deliberately:

```sh
AI_JOBS_LOCAL_ENABLED=true uv run uvicorn intentcut.backend.app:create_app \
  --factory --host 127.0.0.1 --port 8000 --no-proxy-headers
```

Use a CLI client directly against `http://127.0.0.1:8000`. The guard requires an
actual loopback ASGI peer and a loopback Host (`127.0.0.1`, `localhost`, or `[::1]`).
It refuses Origin headers, browser fetches with Sec-Fetch-Site other than `none`,
and Forwarded, X-Forwarded-*, or Via headers. It does not infer authorization from
forwarded addresses. Invalid UUIDs and bodies use the existing sanitized 422 format.

**Do not expose this app publicly or through a reverse proxy/tunnel.** Disable
Uvicorn proxy-header rewriting. A local proxy that strips forwarding headers is
indistinguishable from a trusted local caller. This guard is not authentication.
The existing project/media endpoints retain their behavior and have no user-auth
layer either. A browser frontend, public API, or multiple untrusted users require
identity and project authorization before deployment. This milestone provides no
setting that enables public AI API access or uploaded-media processing.

## Implemented endpoints

| Method and path | Behavior in explicit local mode |
| --- | --- |
| `POST /projects/{project_id}/ai-jobs` | Validate first-cut request and media ownership, then return 503; no row created |
| `GET /projects/{project_id}/ai-jobs/{job_id}` | 200 with public status, timestamps, attempt count, safe error code |
| `GET /projects/{project_id}/ai-jobs/{job_id}/artifacts` | 200 with registered artifact metadata and relative download URLs |
| `GET /projects/{project_id}/ai-jobs/{job_id}/artifacts/{artifact_id}` | 200 with verified MP4 or sanitized JSON; missing registration is 404; unavailable file is 503 |

All AI API responses include `Cache-Control: private, no-store` and
`X-Content-Type-Options: nosniff`, including validation and access failures.
Missing jobs, wrong-project jobs, and artifacts from other jobs return the same
404 response. An existing job without artifacts returns `{"items": []}`. Legacy
succeeded jobs are not backfilled. Listing never scans storage or reveals orphans.

### Job creation is intentionally unavailable

The real adapter consumes cached `clip_b` evidence and does not resolve uploaded
media IDs. Accepting arbitrary uploads into that queue would risk rendering
unrelated footage. M2B.8 therefore fails closed even in local mode. There is no
cached-evidence bypass and no HTTP 202 success path yet. The existing repository
creation method remains available to trusted worker tests and development tools.

Request example (replace IDs with existing project/media UUIDs):

```http
POST /projects/11111111-1111-4111-8111-111111111111/ai-jobs
Content-Type: application/json

{
  "kind": "first_cut",
  "intent": "Make a concise travel story",
  "target_seconds": 30,
  "media_ids": ["22222222-2222-4222-8222-222222222222"]
}
```

`intent` is trimmed and must contain 1–1000 characters. `target_seconds` must be a
finite JSON number greater than zero and at most 120 (strings and booleans are
rejected). Require 1–10 unique media UUIDs, all in the specified project; unknown
fields such as paths, evidence directories, or lease tokens are rejected. Missing
projects/media and media belonging to another project return 404. Invalid input
returns 422 `invalid_request`. Valid input receives:

```http
HTTP/1.1 503 Service Unavailable
Content-Type: application/json

{
  "code": "upload_inference_unavailable",
  "message": "Job creation is unavailable until uploaded-media inference is integrated."
}
```

### Status and artifact examples

```json
{
  "id": "33333333-3333-4333-8333-333333333333",
  "status": "running",
  "created_at": "2026-10-28T00:00:00Z",
  "updated_at": "2026-10-28T00:00:01Z",
  "started_at": "2026-10-28T00:00:01Z",
  "finished_at": null,
  "attempt_count": 1,
  "error_code": null
}
```

Statuses are `queued`, `running`, `failed`, and `succeeded`. Error codes allow
`processing_failed` and `worker_lease_expired`; unknown persisted codes map to
`processing_failed`. Responses never serialize request payloads, lease tokens,
lease expiry, credentials, internal directories, or raw exception diagnostics.

```json
{
  "items": [
    {
      "id": "44444444-4444-4444-8444-444444444444",
      "kind": "video",
      "size_bytes": 43210,
      "download_url": "/projects/11111111-1111-4111-8111-111111111111/ai-jobs/33333333-3333-4333-8333-333333333333/artifacts/44444444-4444-4444-8444-444444444444"
    }
  ]
}
```

Video responses use `video/mp4`, JSON uses `application/json`, and both use
`Content-Disposition: attachment` with a server-generated UUID filename and the
appropriate extension. A sanitized storyboard example:

```json
{
  "target_seconds": 30.0,
  "total_seconds": 5.0,
  "cuts": [{"window_index": 0, "start_seconds": 0.0, "end_seconds": 5.0}]
}
```

Only typed numeric timeline fields are public. All other fields, including titles,
rationales, editorial reasons, source paths, nested metadata, and unknown future
fields, are omitted. Free text is excluded because it may contain private paths
or credentials. Legacy JSON objects that do not satisfy this timeline contract
return 503 `artifact_unavailable`; the original stored artifact is never modified.
Listed `size_bytes` is the registered original size. JSON download Content-Length
reflects the sanitized response and can differ from that original size.

## Storage and reliability

Downloads accept only artifact UUIDs. The repository scopes artifact discovery
through the job's project. Storage requires the exact canonical key for the
requested project and artifact, then opens every component using the same
no-symlink, descriptor-relative regular-file opener used by M2B.7 publication.
Traversal, absolute keys, cross-owner keys, symlinks, FIFOs, and other special
files fail closed. Missing, truncated, oversized, or checksum-mismatched objects
return a generic 503 `artifact_unavailable` before sending file bytes.

Each download makes a bounded private snapshot and compares its size and SHA-256
with the registered metadata. This prevents a later pathname replacement or
source mutation from changing the download. MP4 validation/decode remains in the
publisher; HTTP only checks integrity and the MP4 header. Storyboard snapshots
are additionally parsed, validated, and sanitized. Small snapshots use memory;
large ones spill to private temporary files, closed on completion or send failure.

Storage still requires a trusted private local filesystem. Each download costs a
full copy and hash before streaming; range/conditional requests are not implemented
(the server sends the full 200 representation). Disk capacity and concurrent
request budgets require operational sizing before broader use. No schema change,
new queue infrastructure, janitor, or provider calls were added. Existing orphan
and uncertain-commit reconciliation limitations remain as documented in M2B7.

## M2B.9 remaining work

1. Add real identity and project authorization before public or multi-user access;
   protect project/media routes too and design browser access deliberately.
2. Resolve authorized uploaded media through safe storage, generate evidence and
   windows for those exact files, and bind evidence to immutable media IDs and
   fingerprints. Eliminate implicit shared `clip_b` selection and stem collisions.
3. Update the processor contract to consume those media IDs and verified evidence,
   retain bounded duration/media validation, and keep provider work in the worker.
4. Enable transactional queued-job creation through `Database.create_ai_job` only
   when that processing contract is ready. Return 202 with job ID, status, and
   status URL; address retries/idempotency and request admission budgets.
5. Add an upload → queued job → worker → published artifact → download integration
   test using fake provider responses and local FFmpeg. Keep M2B.7 fencing and
   atomic artifact registration intact. Plan orphan reconciliation and retention.

Tests use TestClient, fake processors, real local FFmpeg artifacts, and isolated
PostgreSQL schemas. No Meta API calls are made. Run:

```sh
uv run ruff check .
uv run pytest -q
git diff --check
```
