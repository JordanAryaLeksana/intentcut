# M3.4 — Persistent manual editing and MP4 re-rendering

Implemented on `feat/m3-frontend`, preserving the pre-existing working tree. No commits, pushes, dependency installations, arbitrary trimming, AI chat revision or paid provider calls were performed.

## API and persistence

The existing opt-in loopback/browser-origin access boundary now also protects `/projects/{project_id}/edit-draft`. This remains a local development application, not authenticated multi-user production hosting. All references are checked against their project; cross-project references return 404. CORS permits PUT for the new save operation.

| Method | Path | Contract |
| --- | --- | --- |
| GET | `/projects/{project_id}/edit-draft` | `{ "draft": null }` or `{ "draft": { revision, base_job_id, base_artifact_id, window_indices, updated_at, storyboard } }` |
| PUT | same | `{ expected_revision, base_job_id, base_artifact_id, window_indices }`; returns saved draft object, or 409 `draft_conflict` |
| POST | `/projects/{project_id}/edit-draft/renders` | `{ revision }`; returns 202 `{ id, status, status_url }` |
| GET | same | `{ items: [{ job_id, revision, status }] }`, latest 100 render jobs |

Status, progress, artifact listing, verified storyboard download and MP4 download reuse the existing `/projects/{project_id}/ai-jobs/{job_id}` APIs. Existing first-cut endpoint contracts remain unchanged.

`window_indices` is an ordered, unique subset of the exact base artifact's cuts. Browser-provided paths, URLs, trim ranges and extra fields are rejected. The server resolves the validated published ranges, source IDs and immutable first-cut fingerprints. It rejects non-succeeded/non-first-cut bases, fabricated cuts, missing ownership and invalid source bounds. Empty drafts may be saved, but cannot be rendered.

One `edit_drafts` row per project stores the current head, base job/artifact foreign keys, monotonically increasing persistent revision, ordered cut IDs and update time. A short project-row lock serializes first insert, conflict-safe updates and render admission. Inference, extraction and rendering never hold that lock/transaction.

Render jobs retain an immutable validated EditPlan snapshot and source fingerprints in the existing private `ai_jobs.request_payload`, with `pipeline_version: manual_v1` and `draft_revision`. A partial unique index deduplicates admission per project/revision. Repeated admission returns the existing job; explicit admission of a failed job requeues that same immutable snapshot. Successful older outputs remain immutable and available.

## Renderer and frame manifest

`ManualRenderProcessor` revalidates the base artifact, securely snapshots source media through existing no-follow storage, verifies original SHA-256 fingerprints, and re-extracts only the admitted published ranges. It never invokes video understanding, story selection, Muse or another inference provider.

It reuses `VerticalVideoRenderer`, FFmpeg normalization, audio delay/silence handling, AAC stereo output validation and full playback decoding. The existing lease-aware worker supplies heartbeat, ownership fencing, recovery and atomic artifact registration. Progress reports only actual preparing, extracting, rendering and publication stages. The normal worker dispatches manual jobs before AI processing; `intentcut-ai-worker --manual-only` can process/recover only manual jobs without constructing an OpenAI client. The regular processing loop still runs inside the OpenAI client context.

Manual rendering measures decoded frame counts and CFR timestamps for every normalized segment. Segment counts must match the renderer's frame-rounded duration; the final output's measured count must equal their sum and every final timestamp must match its 30 FPS frame index. The existing output validator additionally checks H.264 720×1280, yuv420p, AAC stereo/48 kHz, duration, timestamps and decodability.

The immutable storyboard artifact includes an allowlisted `render_manifest` with:

- `fps`, `total_frames`, `draft_revision`, exact base job/artifact IDs.
- Ordered cuts with real source IDs/ranges and inclusive `output_start_frame` / exclusive `output_end_frame`.

The public response schema validates contiguous boundaries, total frames, source correspondence and duration. No filesystem paths, private evidence or AI prose are included. No new artifact kind/table was necessary. Source duration sums are not presented as output timecodes.

## Frontend

Real Save Draft and Render Updated Cut controls replace memory-only status. Saved revision is distinct from local edit counter and rendered revision. Rendering is enabled only for a nonempty sequence matching the confirmed saved version. Saving completion does not overwrite edits made while the request was in flight.

Restoration precedes AI artifact ingestion. A saved reordered/removed sequence restores even without a session job ID; source preview can fall back to its base job. Refetch and new-result protections remain in place. Conflicts retain local edits and offer an explicit discard-and-reload operation. Unsaved edits and undo history remain session memory; only confirmed saves survive reload.

A Program Monitor selector switches between the original first cut and saved render versions. Render status/progress uses existing 2-second job queries and stops on terminal status; version listing also polls only while jobs are active. Captions distinguish selected output from current draft changes. Native MP4 controls, on-demand blob loading and download links are retained. Inspector and timeline still share selection and working reorder/remove actions. Trim inputs and a frame-accurate interactive playhead are not introduced.

## Migration and runtime

`scripts/migrations/002_edit_drafts.sql` creates the draft table and partial render-admission index idempotently. It was applied **only to the verified local development database** `intentcut` on loopback port 5432, after verifying Docker Compose ownership and confirming no queued/running jobs. No M3.2A migration was repeated.

Backup: `.local/backups/m34-20261029T171941Z/intentcut.dump` (14,588 bytes), SHA-256 `436b4f89dd88e3057d5be5bb5753fc6983d895fb70a65a00dc4fdfc88d919609`. Restricted backup permissions; `pg_restore --list` and full archive extraction verified. Migration was applied twice transactionally; full-row fingerprints confirmed all 5 projects, 18 assets, 12 existing jobs and 8 existing artifacts unchanged. Verification and runtime records are in the same backup directory. API and existing continuous worker were gracefully restarted with their previous entrypoint/options.

Other environments must explicitly run migration 002 transactionally before enabling these endpoints. There is no automatic startup migration.

## Verification results

- Relevant backend PostgreSQL/real FFmpeg and unit regression run: **166 passed**, zero failures/skips, in 40.75 seconds. Includes manual save/load, concurrent conflict, project isolation, invalid IDs, additive migration creation/idempotency, immutable revision render, measured frame manifests, color/order change, removal, preserved older artifacts, changed source failure, expired lease fencing/recovery, manual-only claims, provider-free CLI, original worker client lifecycle, existing first-cut flow and renderer/audio regressions.
- Final scoped Ruff: passed for all backend source/tests changed here.
- Frontend automated checks: **65 passed**, zero failures/skips. Includes six new persistence/version tests and existing editing, status, recovery, API/media and storyboard tests. Test harnesses were updated for the new React Query consumers and restoration state.
- Frontend ESLint and TypeScript: passed.
- One production build, `npm run build -- --webpack`: passed compilation, TypeScript and static generation. Webpack avoids the previously established Turbopack environment issue.
- After that build, a small retry-cache safeguard was added: render admission invalidates the exact job-status query as well as the versions query, so retrying a previously failed job does not leave its terminal cached state visible. A subsequent focused TypeScript/ESLint check passed. The production build and browser smoke were not repeated for that final cache invalidation, respecting the bounded verification request.

One continuous Playwright smoke pass used the actual existing project. Initial navigation had no session job ID, so the known previously completed job ID was restored for editing; no new first-cut job was submitted. Verified selecting/moving the first cut, removing the last, saving revision 1, clearing the legacy session ID, reloading four persisted cuts in the edited order, asynchronous manual rendering, native playback/download bytes, and switching original/manual outputs. The original remained byte-for-byte unchanged.

Screenshots reviewed at 1440×900, 1024×768 and 375×812: `.playwright-mcp/m34-1440.png`, `m34-1024.png`, `m34-375.png`. Desktop document dimensions matched the viewport; mobile had no horizontal overflow and intentional vertical document scrolling. Screenshot review prompted compacting the persistence toolbar and correcting the topbar to describe the selected manual output; these final small UI changes were lint/type/build checked, without repeating the browser session.

### Actual manual-render evidence

Project: `f93aa0e0-4ada-463c-a7c5-086ddeecd4b9`.

- Published order: `[2, 6, 4, 8, 5]`; saved manual order: `[6, 2, 4, 8]`.
- Manual job: `bfdc0ea1-0851-4d83-b26a-bdc367ef8954`, succeeded, draft revision 1.
- Actual output: **443 frames at 30 FPS**, 14.766667 seconds, valid H.264/AAC.
- Measured output frame ranges: `[0,151)`, `[151,262)`, `[262,412)`, `[412,443)`.
- Original video SHA-256: `1e488369491bec020ad4a1836967a6bde27a22d077e4bfaedd3fc2dfe4492d49`.
- Manual video SHA-256: `e43ea4c9021aa3ba2ae53875db587e596c2ad4dc1847f2f40d12b5a4d95b1954`.
- Native playback advanced with no media error. Original-version switching confirmed the original hash was unchanged. The download blob was verified; OS file-save completion was not exercised.

`M3_4_RENDER_EVIDENCE.json` contains the actual public frame manifest and independent FFmpeg validation result. Separately, deterministic real red/blue FFmpeg fixtures assert that the manually reordered output begins red then blue, differs from the original, and retains valid video/audio.

## Changed files

Backend:

- `src/intentcut/backend/editing/{__init__,service,routes,processor}.py` (new)
- `src/intentcut/backend/storage/{database,database_models}.py`
- `src/intentcut/backend/{app,ai_worker,worker_cli}.py`
- `src/intentcut/backend/shared/http_security.py`
- `src/intentcut/backend/artifacts/schemas.py`
- `src/intentcut/media/{models,render}.py`
- `src/intentcut/media/frame_manifest.py` (new)
- `scripts/migrations/002_edit_drafts.sql` (new)
- `tests/integration/backend/test_manual_editing.py` (new)
- `tests/unit/backend/test_worker_cli.py`

Frontend:

- `frontend/src/lib/api/editing.ts` (new)
- `frontend/src/features/studio/{draft-persistence.tsx,use-editing.ts}` (new)
- `frontend/src/features/studio/store/use-draft-store.ts`
- `frontend/src/features/studio/{draft-timeline,narrative-timeline,program-monitor,studio-top-bar,studio-dock,studio-shell}.tsx`
- `frontend/src/features/studio/studio.css`
- `frontend/src/features/studio/__tests__/persistent-editing.test.mjs` (new)
- `frontend/src/features/studio/__tests__/{draft-timeline,narrative-timeline}.test.mjs`
- This report, `M3_4_RENDER_EVIDENCE.json` and three smoke screenshots.

## Limits and intentionally deferred work

Only reorder/remove of existing published cuts is supported. Arbitrary trim, source replacement, chat revision and M3.5 are not implemented. Current draft head is persisted; complete saved-draft history is not a separate table. Submitted render snapshots and successful output versions are retained. The version listing returns the latest 100 jobs; older output IDs remain accessible through the existing artifact API. Empty drafts cannot render.

This uses the existing local access model, with project scoping rather than production user authentication. Unsaved edits/undo history do not survive reload. There is no automatic merge on revision conflict. The frame manifest is published for reliable output mapping; native playback remains the UI transport, with no new timeline seek synchronization. Editorial reasons remain absent from the intentionally sanitized public API. Fresh upload and paid AI generation were not manually exercised; their relevant existing automated tests passed.

Stopped before M3.5.
