# Batch 5 — Muse Image Creative Studio (branch terisolasi)

## A. Fitur yang diimplementasikan

AI Visuals terintegrasi pada dock Studio: prompt, preset Thumbnail/Cover/Poster,
mode generate/edit, referensi image yang sudah dipublikasikan atau frame video
rendered terpilih, queued/running/terminal status, image preview/download, saved
asset history, dan Set as Cover persistent dengan optimistic conflict. Current
project cover benar-benar ditampilkan dari state server setelah refresh.

Integrasi provider adalah adapter HTTPS nyata untuk Muse Image. Pengujian memakai
provider mock dan PNG nyata dari FFmpeg. Tidak ada paid inference atau klaim bahwa
fixture adalah hasil generasi AI live. Title cards ke timeline/MP4 tidak dibangun.

## B. Arsitektur dan data flow

Baseline branch ini adalah 1e92cfc4543c4cc67ed5862e5f4ee5cc45defaf2, checkpoint
Batches 1–3 yang diverifikasi sudah dipush. Worktree /tmp/intentcut-muse-image-b5
terisolasi dari working directory Batch 4 dan branch SAM. Tidak menyalin perubahan
Batch 4 yang belum committed dan tidak melakukan merge otomatis.

Studio → VisualRequest UUID/project → source artifact ownership/checksum validation
→ bounded PostgreSQL admission → typed image_generate_v1 worker → durable provider
reservation → fixed-host Meta HTTPS → strict PNG response parser → decoded image
validation → immutable private cache with fenced DB pointer → Batch 2 publisher →
atomic succeeded/artifact → verified image download. Project cover merupakan FK
ke immutable artifact + SHA, bukan copy/overwrite file.

Reference edit hanya mengambil artifact dari project yang sama dan job succeeded.
Image diverifikasi melalui existing snapshot; video diprobe dan satu frame diekstrak
FFmpeg. Frame_seconds harus berada di dalam durasi. Dimensi video dibatasi sebelum
extraction. Job mem-pin parent ID/hash dan frame_seconds; source file/path/URL tidak
pernah diterima dari browser.

## C. Inventaris file

Status relatif baseline; tidak ada file dihapus.

| Path | Status | Responsibility / alasan |
|---|---|---|
| src/intentcut/ai/image.py | Added | Official Muse Image JSON adapter, bounded base64 response, no retry/redirect |
| src/intentcut/backend/visuals/__init__.py | Added | Namespace feature |
| src/intentcut/backend/visuals/contracts.py | Added | Strict generate/edit/source/preset/cover contracts |
| src/intentcut/backend/visuals/source.py | Added | Authorized image and rendered-frame extraction |
| src/intentcut/backend/visuals/repository.py | Added | Lease-fenced durable paid-call reservation/cache pointer |
| src/intentcut/backend/visuals/processor.py | Added | Provider orchestration, validation, immutable cache/recovery |
| src/intentcut/backend/visuals/service.py | Added | Admission/dedupe/budget/history and persistent cover selection |
| src/intentcut/backend/visuals/routes.py | Added | Scoped visuals and cover APIs |
| src/intentcut/backend/storage/database_models.py | Modified | ProjectCover persistence model |
| scripts/migrations/006_project_covers.sql | Added | Additive idempotent cover table; no migration applied |
| src/intentcut/backend/jobs/dispatch.py | Modified | IMAGE_GENERATE → ImageArtifactResult explicit mapping |
| src/intentcut/backend/jobs/progress.py | Modified | generating_image / validating_image stages |
| src/intentcut/backend/artifacts/derived.py | Modified | Expected image kind for new pipeline |
| src/intentcut/backend/contracts.py | Modified | Safe image failure/outcome codes |
| src/intentcut/backend/shared/settings.py | Modified | Independent enable flag, count/time budgets |
| src/intentcut/backend/ai_worker.py | Modified | Direct image processor capability fencing |
| src/intentcut/backend/worker_cli.py | Modified | --image-only and optional normal-worker registration |
| src/intentcut/backend/app.py | Modified | Wire scoped image/cover router before UUID job route |
| frontend/src/lib/api/visuals.ts | Added | Typed response validation and project-only API operations |
| frontend/src/features/studio/visuals/visuals-panel.tsx | Added | Functional image workflow/current cover/history/verified blobs |
| frontend/src/features/studio/studio-dock.tsx | Modified | AI Visuals tab and keyboard support |
| frontend/src/features/studio/store/use-draft-store.ts | Modified | Project-specific visuals tab selection |
| frontend/src/features/studio/studio.css | Modified | Existing-token responsive form/image layout |
| frontend/src/lib/api/contracts.ts | Modified | Explicit image progress stage union |
| frontend/src/lib/api/job-progress.ts | Modified | Parse actual backend image stages |
| frontend/src/features/studio/ai-director/processing-state.ts | Modified | Safe image-stage descriptions |
| frontend/src/features/studio/__tests__/visuals.test.mjs | Added | API, recovery, conflict, isolation, accessible form tests |
| frontend/src/features/studio/__tests__/workspace-shell.test.mjs | Modified | Third-tab keyboard navigation regression |
| tests/unit/backend/test_image_provider.py | Added | Official request/response, errors, no-repeat lifecycle |
| tests/integration/backend/test_visual_assets.py | Added | PostgreSQL/FFmpeg publication, source lineage, cover/recovery |
| BATCH_5_MUSE_IMAGE.md | Added | Engineering report, evidence, rollout and integration notes |

## D. Adapter, APIs, classes dan provenance

Official references inspected:

- https://dev.meta.ai/docs/image-generation
- POST https://api.meta.ai/v1/images/generations
- POST https://api.meta.ai/v1/images/edits

Generate uses JSON {model:muse-image-1.0,prompt,n:1,size,response_format:b64_json,
output_format:png}. Edit uses Meta-documented JSON images:[{image_url:dataURL}],
not a fabricated OpenAI multipart contract. Three grounding tools are disabled
explicitly and reasoning_strength=low. Size is an aspect-ratio hint, not guaranteed
pixel dimensions; UI says this and never fabricates output resolution.

Response must echo output_format=png and exactly one data[].b64_json. URL output,
invalid base64, wrong encoding/count and oversized output fail closed. Full decode,
codec/dimensions/frame-count validation reuses Batch 2 FFprobe/FFmpeg validator.

- MuseImageClient: fixed hostname, one request, per-call connection/response close.
- parse_image_response: allowlist only image bytes, not diagnostics/reasoning/URLs.
- VisualRequest: UUID, prompt≤2000, supported preset/mode and typed source/frame.
- authorized_source: verified snapshot, image validation, bounded FFmpeg frame.
- reserve_call/mutate_payload: commit marker before HTTP and fence cached pointer.
- VisualProcessor: immutable random cache filename/hash; cache recovery skips paid
  inference; unknown reserved-but-uncached outcome stops rather than paying again.
- VisualService: project-row serialization, same UUID/payload idempotency, same
  payload dedupe even after failure, one active job/project, default three jobs/project.
- ProjectCover: project PK, image artifact/job FK, SHA, revision. Set as Cover
  verifies real bytes, checks expected_revision, returns 409 on stale selection.
- VisualImage: downloaded verified blob, abort/revoke lifecycle and project/job/asset
  key prevents stale previews; saved cover is rendered from the server reference.

Public API under /projects/{project_id}/ai-jobs/visuals:

- POST empty suffix: request_id,prompt,preset,operation,optional source_artifact_id,
  optional frame_seconds; returns accepted id/status/status_url.
- GET empty suffix: safe job/asset metadata and persisted current cover.
- PUT /cover: artifact_id,expected_revision; saves selected project image.
- Existing GET job status and artifact routes retrieve outputs.

Model ID, operation, preset, parent ID/SHA, frame position and producing job persist
in the immutable submitted job snapshot. File artifact identity/hash remain immutable.
No private storage paths or provider responses are exposed. History stores no fake
rendered MP4 or title-card integration.

## E. Skills dan dependencies

Used skill: ui-ux-pro-max.
Path: /tmp/intentcut-muse-image-b5/.agents/skills/ui-ux-pro-max/SKILL.md.
Purpose: labelled forms, visible submission/error feedback, accessible tabs,
responsive dark Studio controls using existing tokens. AGENTS.md, frontend AGENTS
and the installed Next.js use-client guide were read. A shadcn MCP consultation
was attempted but stalled/aborted; shared-session @shadcn textarea discovery was
already verified by parent. Existing native controls used; no components installed.

No Python/npm/OS dependency added, no package/lockfile changes. Python stdlib HTTPS,
base64 and existing FFmpeg/Pydantic/PostgreSQL are sufficient. Worktree uses root
venv read-only with explicit PYTHONPATH; __file__ proof confirmed imports from this
worktree. frontend/node_modules is an ignored dependency symlink, not copied source.

## F. Engineering decisions

PNG-only/n=1 deliberately narrows the supported official API to fit existing safe
artifact contracts. No provider URL downloads means no additional SSRF surface.
Optional parent for text generation; parent required for editing. Video-frame edit
sends just an authorized frame, never entire footage or arbitrary external URLs.

One queue/worker architecture retained. Cache filenames are UUIDs and never replaced;
only a lease-fenced DB pointer grants recovery authority. fsync persists file and
cache directory. Marker-before-HTTP is conservative at-most-once admission: crash
before sending can sacrifice a request, rather than duplicate a paid call. Session/
request UUID is not claimed to be provider idempotency. No automatic HTTP retries.

Cover selection is an actual project record and consumed by the Studio cover image.
It is cover-only, not an EditPlan segment. Title-card renderer changes were rejected
for this slice because they would change manual render frame/audio composition and
need an independently reviewed media contract.

## G. Verification

Executed from this worktree, with root dependencies only:

```sh
PYTHONPATH=/tmp/intentcut-muse-image-b5/src /home/jordan/Documents/Hackaton-Meta/intentcut/.venv/bin/python -m pytest tests/unit/backend/test_image_provider.py tests/unit/backend/test_worker_cli.py tests/unit/backend/test_job_dispatch.py -q --tb=short --basetemp=/tmp/b5-unit
```

62 passed, zero failed/skipped (0.88 s), termasuk guard FFmpeg/FFprobe sebelum admission provider. Provider HTTP is mocked; actual PNG decode
and artifact publication are checked by PostgreSQL/FFmpeg tests separately.

Frontend commands (cwd frontend):

```sh
node --import tsx src/features/studio/__tests__/visuals.test.mjs
node --import tsx src/features/studio/__tests__/workspace-shell.test.mjs
node --import tsx src/features/studio/__tests__/processing-timeline.test.mjs
npm run lint
./node_modules/.bin/tsc --noEmit
npm run build -- --webpack
```

10 + 4 + 13 = 27 case tests passed; ESLint exit0; typecheck exit0; production build
exit0 with compiled/TypeScript/static generation/build traces complete. Initial
fresh-tree typecheck lacked generated LayoutProps; build typegen resolved it.
tsx CLI IPC was sandbox-blocked; direct node --import tsx runs actual case tests
without IPC. node --import tsx --test reported file wrappers only and is not used
for the case totals. A cwd command error was corrected; no blocked result called pass.

Ruff on all changed backend/tests: All checks passed. git diff --check clean.
Verifikasi final PostgreSQL/FFmpeg: **56 passed, 0 failed/skipped (43.14 s)**.
Perintah suite: `pytest tests/integration/backend/test_visual_assets.py tests/integration/backend/test_uploaded_job_flow.py tests/integration/backend/test_manual_editing.py tests/integration/backend/test_revision_proposals.py -q --tb=short`.
Dieksekusi melalui `uv run --no-sync python` dengan import source worktree eksplisit,
TEST_DATABASE_URL privat, schema fixture terisolasi, dan cache pytest dinonaktifkan.
Sepuluh kasus visual mencakup PNG nyata, publikasi dan retrieval, lineage frame,
wrong-project, checksum, cover 409/reload, marker/cache recovery dan stale lease.
Regresi first-cut, manual rendering, dan AI revision ikut lulus. Tidak ada schema
development atau provider live yang disentuh. Ketersediaan FFmpeg/FFprobe diperiksa
sebelum admission/worker memanggil provider agar biaya tidak terbuang karena tool hilang.

## H. Security/model-access/reliability limits

Feature default disabled. Credentials server-side only, no key in frontend/config
response. Project UUID is not user authentication: existing local-only middleware
remains the available access boundary. Do not publicly expose before auth review.

Limits: one active image job/project, default three admitted jobs/project, one image,
≤16MiB decoded bytes, dimensions≤8192 per side/16,777,216 pixels, bounded response
24MiB and timeout240s. This is not a global currency ledger. New projects can bypass
per-project spending count; public deployment still needs authentication/account limits.

No live Muse Image entitlement, quality, latency, actual edit fidelity or provider
rate-limit verification. No browser smoke: migration004 remains pending and a new
incompatible development runtime was not started. Blob lifecycle/responsive UI
has automated tests and build verification, not live desktop/mobile screenshots.

## I. Database migrations

006_project_covers.sql is additive/idempotent and standalone from baseline:
requires migration004/base tables; does not depend on or copy Batch4 migration005.
No migration applied development/production. Operator must approve backup/migration
and apply004 then006 before deploying this branch. create_all is not an ALTER
migration mechanism. A separate caption branch may require005 when later integrated.

## J. Git and integration

Branch feat/muse-image-b5; baseline1e92cfc. No Batch4 root changes, no SAM branch
changes, no automatic merge. Shared integration conflicts expected in app wiring,
worker registry/CLI, models/settings/contracts/progress, StudioDock/store/CSS and
frontend stage unions. Resolve only in a reviewed integration branch after each
feature's gate passes. This branch does not claim caption-specific compatibility:
Batch4 source is absent from the stable shared baseline and was not copied.

Final source/staged audit excludes .env, footage, generated images, databases,
backups, node_modules, builds and caches. Commit and push outcome is reported to
parent after tests/security gates; no force push or main/master merge.

## K. Remaining production work

Approve migrations; integrate B4/B5/B6 shared files explicitly; run one controlled
paid Muse Image generation/edit test with account access; perform focused browser
smoke and persistent-cover refresh check; complete authentication/global cost
admission and deployment hardening separately. Title cards, multi-image composition,
WebP output, arbitrary image URLs and new autonomous features remain deferred.
