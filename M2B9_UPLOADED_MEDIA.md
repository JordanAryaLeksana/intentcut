# M2B.9: uploaded footage to persistent first-cut MP4

The backend now processes the media UUIDs submitted through the API, including
multiple uploaded videos. There is no global `clip_b` cache or filename/stem lookup
in the worker. Existing M2A scripts remain available as standalone development
tools, but the backend never invokes their cached-evidence entry points.

Automated acceptance runs real PostgreSQL, actual M1B uploads, local extraction and
M1A rendering, M2B.7 publication, and M2B.8 downloads. Only Muse responses are faked.
Live Meta acceptance is a separate opt-in step and has not been executed as part
of this implementation.

## Execution flow and code

```mermaid
flowchart LR
    A[Upload via M1B] --> B[Project media records and private originals]
    B --> C[POST: ownership, budgets, source SHA-256]
    C --> D[Queued PostgreSQL job: HTTP 202]
    D --> E[Worker claim and heartbeat]
    E --> F[Private source snapshots and temporal windows]
    F --> G[Muse understanding and fingerprinted evidence]
    G --> H[Story Director selects window indices]
    H --> I[Backend validates EditPlan]
    I --> J[M1A render and full decode]
    J --> K[M2B.7 publication and fenced atomic completion]
    K --> L[Registered MP4 and sanitized storyboard downloads]
```

- `backend/ai_media_inputs.py`: configuration readiness, metadata-based budgets,
  safe source fingerprints, and the private persisted request contract.
- `backend/ai_processing_adapter.py`: uploaded-media orchestration using existing
  repository, storage, probe, temporal planner, window extractor, and M1A renderer.
- `ai/muse.py`: M2A's existing file-upload and structured Muse understanding call,
  extracted from `scripts/analyze_windows.py` for reuse.
- `ai/video_understanding.py`: window identities, bounded evidence cache, Pydantic
  revalidation, and grounding through the existing `to_window_evidence` function.
- `ai/story_director.py`: the existing structured director call, shared with the
  script, plus multi-source `EditPlan` construction against trusted window records.
- `backend/worker_cli.py`: a finite local worker command using the existing
  heartbeat, recovery, publisher, and repository lifecycle.

No table migration is required. New private request fields live in the existing
JSONB payload. The API forbids clients from supplying those fields. Old queued
cached-evidence payloads fail validation; they are never silently reinterpreted.
The obsolete real-adapter constructor taking an evidence directory was removed.

## Local configuration and exact commands

Install from the project root, initialize the existing PostgreSQL schema, and use
the same `.env`/environment and storage root in the API and worker processes:

```sh
uv sync
uv run intentcut-init-db
export AI_JOBS_LOCAL_ENABLED=true
export AI_PROCESSING_ENABLED=true
# Configure MODEL_API_KEY privately in the environment or .env; never commit it.
uv run uvicorn intentcut.backend.app:create_app --factory \
  --host 127.0.0.1 --port 8000 --no-proxy-headers
```

`AI_JOBS_LOCAL_ENABLED` and `AI_PROCESSING_ENABLED` default to false. Creating jobs
requires both flags, a nonblank `MODEL_API_KEY`, and discoverable `ffmpeg` and
`ffprobe` executables. This is an offline configuration check, not a claim that
provider credentials are valid or the provider is reachable. Provider failures
produce safe failed-job codes. No inference occurs in the HTTP handler.

The AI API remains restricted to direct loopback clients. Origin-bearing browser
requests, nonlocal peers/Hosts, and forwarding headers are rejected. Keep proxy
header rewriting disabled. There is still no user identity or per-user project
authorization, and the existing project/media routes have no authentication.
**Do not deploy this app publicly or expose it through a tunnel/proxy.**

Create a project and upload footage (substitute the returned project UUID):

```sh
curl --fail-with-body http://127.0.0.1:8000/projects \
  -H 'Content-Type: application/json' -d '{"name":"My first cut"}'

curl --fail-with-body http://127.0.0.1:8000/projects/PROJECT_UUID/media \
  -F 'files=@/absolute/path/first.mp4' -F 'files=@/absolute/path/second.mp4'
```

Create the job with the returned media UUIDs, in the desired input order:

```sh
curl --fail-with-body http://127.0.0.1:8000/projects/PROJECT_UUID/ai-jobs \
  -H 'Content-Type: application/json' \
  -d '{"kind":"first_cut","intent":"Establish the scene, then show the action","target_seconds":15,"media_ids":["MEDIA_UUID_1","MEDIA_UUID_2"]}'
```

Successful response: HTTP **202 Accepted**, `Location` pointing to the status URL:

```json
{
  "id": "33333333-3333-4333-8333-333333333333",
  "status": "queued",
  "status_url": "/projects/11111111-1111-4111-8111-111111111111/ai-jobs/33333333-3333-4333-8333-333333333333"
}
```

Unconfigured processing returns 503 `upload_inference_unavailable`. Invalid public
input returns 422 `invalid_request`. Missing/cross-project media returns 404.
Missing, changed-size, or unsafe source objects return 422 `source_unavailable`;
processing-budget failures return 422 `processing_limit`. Admission opens originals
through safe storage and fingerprints bounded bytes; it does not run FFmpeg or
hold a database transaction during filesystem reads. FFprobe metadata already
validated by ingestion supports admission planning; the worker re-probes its own
immutable snapshots before any Muse request.

Run a single targeted job in another terminal with the same configuration:

```sh
uv run intentcut-ai-worker --job-id JOB_UUID
```

Or drain a bounded number of available jobs:

```sh
uv run intentcut-ai-worker --max-jobs 3
```

Default is one queue item; maximum is 100 per invocation. The command stops when
no job is available; it does not poll indefinitely. It recovers one expired lease
before each claim. Default recovery allows one total attempt; `--max-attempts 2`
(or 3) explicitly permits retries after expiry. Failed jobs are terminal and are
not automatically retried. `--job-id` scopes both recovery and claiming, preventing
a smoke run from spending on unrelated queued work. SIGINT closes resources and
stops heartbeats; an interrupted running job is handled by lease recovery later.
CLI success means the bounded worker ran; inspect job status for processing success.

Poll status and list outputs:

```sh
curl --fail-with-body http://127.0.0.1:8000/projects/PROJECT_UUID/ai-jobs/JOB_UUID
curl --fail-with-body http://127.0.0.1:8000/projects/PROJECT_UUID/ai-jobs/JOB_UUID/artifacts
curl --fail-with-body --output first-cut.mp4 \
  http://127.0.0.1:8000/projects/PROJECT_UUID/ai-jobs/JOB_UUID/artifacts/VIDEO_ARTIFACT_UUID
```

Artifact URLs are generated from registered IDs. Responses retain explicit MIME
types, attachment filenames, `Cache-Control: private, no-store`, and `nosniff`.
Missing/corrupt artifacts return safe errors, and downloads verify size/SHA-256
before streaming a private snapshot. They never reopen a client-selected path.

## Grounding and EditPlan

1. POST resolves every media UUID through the project-scoped repository, rejects
   duplicate/malformed references, preserves their order, and records server-read
   SHA-256 fingerprints in the private job payload.
2. The claimed worker resolves ownership again. It copies each safely opened
   original into `.jobs/JOB_UUID/attempt_NUMBER_LEASE_UUID/MEDIA_UUID/source`,
   verifies the fingerprint and size, and re-probes metadata. Original filenames
   never determine workspace or window paths, so identical filenames cannot clash.
3. The existing deterministic temporal planner covers each admitted source in
   windows of `min(5, target_seconds)` seconds. Each gets a per-source index and a
   unique job-wide index. All source/window preparation and remote-byte budgets
   are checked before paid calls. Corrupt extraction fails with FFmpeg `-xerror`.
4. Muse observes individual extracted clips through the original M2A structured
   request. Scene timestamps must be null; source intervals are attached by the
   backend. Returned timestamps, malformed output, or incomplete responses fail.
5. The director receives grounded evidence and returns only window indices and
   editorial reasons, in playback order. Extra media IDs, paths, and timestamps
   are forbidden by its schema. The backend rejects unknown/duplicate references,
   unowned sources, invalid intervals, and duration overflow.
6. The constructed private `EditPlan` includes actual media UUID, source interval,
   source/window indices, playback order, and editorial reason. Selected clip
   checksums are rechecked before M1A renders them in that order.

The renderer validates H.264, 720×1280, yuv420p, 30 FPS, AAC stereo/48 kHz, timestamps,
and expected duration, then fully decodes before publishing its output. The plan
also budgets each actual extracted clip's duration rounded up to a 30 FPS frame.
The final container can include normal AAC/mux padding within M1A's 0.1-second
validation tolerance. No fine-grained model trimming, transitions, or invented
partial-window boundaries are supported.

Public storyboard JSON retains the numeric timeline plus media UUIDs and playback
order. Titles, rationales, editorial reasons, source paths, and provider metadata
remain private. Example:

```json
{
  "target_seconds": 10.0,
  "total_seconds": 5.0,
  "render_seconds": 5.0,
  "cuts": [{
    "media_id": "22222222-2222-4222-8222-222222222222",
    "window_index": 0,
    "source_window_index": 0,
    "playback_order": 0,
    "start_seconds": 0.0,
    "end_seconds": 5.0
  }]
}
```

## Budgets, caching, and remote cleanup

| Budget | Default / bound |
| --- | --- |
| Media per job | `AI_MAX_MEDIA=4`, configurable 1–10 |
| Total analyzed windows | `AI_MAX_WINDOWS=12`, hard maximum 12 |
| Window duration | At most 5 seconds; reduced for shorter requested outputs |
| Total analyzed source duration | At most 60 seconds with default windows; more source boundaries can reduce this |
| Requested output duration | Greater than 0, at most 120 seconds; a whole window must fit |
| Total source bytes | `AI_MAX_SOURCE_BYTES=536870912` (512 MiB) |
| Per-source ingestion budget | Existing `MAX_FILE_BYTES`, default 128 MiB |
| Input dimensions/rate | At most 4096 pixels per dimension and 120 FPS |
| Remote window file | `AI_MAX_REMOTE_FILE_BYTES=26214400` (25 MiB hard maximum) |
| Total prepared remote bytes | `AI_MAX_REMOTE_TOTAL_BYTES=104857600` (100 MiB) |
| Inference calls per attempt | `AI_MAX_INFERENCE_REQUESTS=13`, maximum 13 |
| Provider retries | 0 SDK retries; 180-second per-request timeout |
| Provider output | 1500 tokens per structured response |

Long videos exceeding the window budget are rejected, not silently sampled or
analyzed without a limit. The 120-second output cap does not imply 120 seconds of
analyzed input under the default 60-second analysis budget. Short targets may be
unprocessable when frame-rounded windows cannot fit; the worker fails clearly
before inference rather than inventing a trim.

The model remains `muse-spark-1.3` at the existing fixed Meta endpoint. A new job
uses **N window-understanding calls plus one director call**, with N ≤ 12. Remote
file create/delete operations are additional HTTP operations, not inference calls.
The same cap applies to each explicitly permitted retry (at most three attempts).
No daily spend quota or automatic provider retry loop is introduced.

Evidence cache entries live under that job's private `.jobs/JOB_UUID/cache` directory.
Cache identity includes media UUID, full-source SHA-256, source interval/index,
window SHA-256, model, prompt hash, schema hash, and cache version. Cache reads use
no-follow regular-file access, have a 128 KiB bound, and revalidate model output
and null timestamps. Changed sources/windows cannot reuse unrelated evidence.
Writes use fresh temporary files and no-overwrite hard-link publication. Retry
attempts can reuse matching evidence but re-run the director. Separate jobs do
not share evidence, and a cache never replaces source verification.

The shared M2A transport deletes every known remote file in `finally`, including
inference/validation failures. Uploads also request a one-hour expiry if cleanup
fails or upload acknowledgement is lost. Provider credentials and remote IDs do
not appear in API responses. Safe job error codes include `source_unavailable`,
`processing_limit`, `invalid_ai_selection`, `provider_unavailable`, and the existing
`processing_failed`/`worker_lease_expired` codes.

## Explicit paid live acceptance

Start the API above, configure a valid `MODEL_API_KEY`, and prepare one or two short
real videos whose total window count fits the budgets. Then explicitly authorize:

```sh
AI_PROCESSING_ENABLED=true uv run python scripts/smoke_uploaded_job.py --live \
  /absolute/path/first.mp4 /absolute/path/second.mp4 \
  --target-seconds 15 --intent 'Establish the location, then show the action'
```

This command creates a real project, uploads real files over HTTP, requires a 202
job response, runs exactly that job with the real Muse client, requires succeeded
status and both registered artifacts, downloads them, checks source UUIDs, validates
MP4 metadata, and fully decodes the downloaded MP4. Downloads are saved under
`.local/smoke/JOB_UUID`. It never prints the API key. API and worker must use the
same database and storage settings. Without `--live`, the script performs no HTTP
or provider requests. A failed provider/model selection can fail this acceptance;
there is no fabricated success or cached-footage fallback.

For two videos no longer than five seconds each and a target that fits both,
expect **2 video-understanding calls + 1 director call**, plus two file uploads and
two deletion attempts. The maximum default inference scope is 13 calls for one
attempt. This implementation does not estimate a monetary price or execute the
paid test automatically.

## Verification and remaining limitations

Run `uv run ruff check .`, `uv run pytest -q`, and `git diff --check`.
Acceptance tests cover one- and two-video uploads, same-name isolation, HTTP 202
persistence, real rendering/full decoding, frame-color playback-order verification,
artifact downloads, configuration gates, source mutations, ownership, malformed
selections, duration/byte/window/call budgets, lease expiry, grounded cache reuse,
provider cleanup, and the actual worker entry point with a fake provider.
Existing publication rollback, fencing, concurrency, and uncertain-commit tests
remain in the full suite.

Remaining limitations:

- Live Meta availability, credentials, and editorial quality require the explicit
  smoke test; deterministic automated tests cannot demonstrate those live facts.
- Local single-trust-domain operation only; no per-user authentication. Existing
  browser-origin restrictions remain. Next.js can now build against the stable
  upload/create/poll/download contracts through a trusted local server-side adapter;
  direct browser access and public hosting need a deliberate auth/access design.
- Whole-window cuts only, short input budgets, and no automatic retries for invalid
  selections. In-flight provider calls are bounded but not forcibly cancelled when
  a lease expires; ownership is rechecked between stages and at publication.
- Source snapshots, windows, and caches are retained for diagnostics/retries. No
  retention janitor, orphan reconciliation automation, idempotent POST, or global
  queue/spend quota is added. Budget disk capacity and clean only reconciled data.
- API creation reads bounded original bytes to fingerprint them. Video downloads
  make complete verified copies before serving; range downloads are unsupported.
- Storage remains a trusted private POSIX filesystem. The publisher continues to
  retain uncertain-commit files for reconciliation and cannot protect against a
  privileged process modifying the storage root.

## M2B.9 file manifest

New files:

- `src/intentcut/ai/muse.py`, `story_director.py`, `video_understanding.py`
- `src/intentcut/backend/ai_media_inputs.py`, `worker_cli.py`
- `scripts/smoke_uploaded_job.py`
- `tests/integration/backend/test_uploaded_job_flow.py`
- `tests/unit/ai/test_evidence_cache.py`, `test_muse_transport.py`, `test_uploaded_story.py`
- `tests/unit/backend/test_worker_cli.py`
- `M2B9_UPLOADED_MEDIA.md`

Existing files changed in this milestone:

- `src/intentcut/backend/ai_processing_adapter.py`, `ai_worker.py`, `ai_jobs.py`,
  `ai_job_service.py`, `ai_job_routes.py`, `api_schemas.py`, `app.py`,
  `backend_settings.py`, `database.py`, `local_media_storage.py`
- `src/intentcut/media/window_extract.py`
- `scripts/analyze_windows.py`, `scripts/story_director.py`
- `tests/conftest.py`, `tests/unit/backend/test_ai_processing_adapter.py`,
  `tests/unit/backend/test_unit_ai_worker.py`
- `pyproject.toml`, `.env.example`, `README.md`, `M2B7_ARTIFACTS.md`, `M2B8_API.md`

The workspace also retains earlier uncommitted M2B.7/M2B.8 files and changes;
those are not newly attributed to M2B.9 here.
