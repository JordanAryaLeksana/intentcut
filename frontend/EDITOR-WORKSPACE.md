# IntentCut Editor Workspace — M3.1 engineering report

## Scope and current inventory

M3.1 implements the workspace shell. Published storyboards remain read-only.
Existing uncommitted work was preserved; no dependencies or backend contracts changed.

| Component | Existing responsibility | M3.1 change |
| --- | --- | --- |
| `studio-shell.tsx`, `studio.css` | Compose Studio panels | Viewport-bounded desktop grid; 65/35 upper workspace/timeline split; independent scrolling |
| `studio-top-bar.tsx` | Project identifier and navigation | Compact toolbar, actual job state, explicit unavailable draft saving, working monitor navigation |
| `media-library.tsx`, `media/persisted-media.tsx` | Local file selection/upload, saved media, AI source selection | Media Pool dock; collapsible local import; existing persistence and selection preserved |
| `program-monitor.tsx`, `ai-director/video-artifact-player.tsx` | Artifact retrieval and native playback/download | Constrained monitor and contained video; native controls and blob cleanup preserved |
| `studio-dock.tsx` | New composition component | Accessible Inspector/AI tabs; selected-source metadata; hidden panels remain mounted |
| `narrative-timeline.tsx` | Fetch and validate published cuts | Source-duration-proportional columns, keyboard-focusable scroll region; published order preserved |
| React Query hooks | Job, media, artifact, JSON queries | Reused; no additional API workflow |
| Zustand editor store | Project-scoped source selection and active job | Reused; no draft history or persistence introduced |

## Verified backend contracts and gaps

- `POST /projects` creates a named project. There is no project GET route in the current project router. Existing project URLs therefore display an identifier, not an invented name.
- `POST /projects/{projectId}/media`, `GET /projects/{projectId}/media`, and `GET /projects/{projectId}/media/{mediaId}` support ingestion and metadata. There is no source streaming or thumbnail endpoint. No fake thumbnails are displayed.
- `POST /projects/{projectId}/ai-jobs` accepts only `kind: first_cut`, intent, target_seconds, and media_ids. It does not accept an editable plan or a render-only operation.
- `GET /projects/{projectId}/ai-jobs/{jobId}` returns queued/running/succeeded/failed, timestamps, attempts, and a safe error code. It exposes no per-stage progress. The shell reports those actual states without percentages or simulated stages.
- Artifact list/download GET routes return registered outputs. Storyboard JSON is sanitized into `PublicStoryboard`/`PublicStoryboardCut`: durations, ordered cuts, media IDs, source ranges, and indexes. Private editorial prose is excluded.
- The Python `EditPlan` contains title, rationale, target_seconds, total_seconds, render_seconds, and `EditCut` entries. It is generated internally, not a manual editing API.
- `RealAIProcessingAdapter` renders selected pre-extracted windows. `VerticalVideoRenderer.render` receives file paths and rounds each input duration to a 30 FPS boundary. It cannot directly render arbitrary browser-supplied trim ranges. Extraction exists earlier in the pipeline, but user-edited plan admission, validation, ownership/bounds checking, and render-only orchestration still need implementation.
- Public storyboard source ranges do not provide exact output frame boundaries. A render manifest must identify source references, frame counts, output offsets, output FPS, and plan version/hash before accurate timeline/source seeking can be promised.

## Architecture decisions

- Desktop uses `100dvh` with bounded grid rows and `min-height: 0` at every scrolling boundary. Each dock scrolls independently. No global body overflow override affects other routes.
- At widths below 900px, panels stack and use document scrolling. Media controls remain reachable; native video preserves its content aspect ratio with `object-fit: contain`.
- Existing React Query caches and Zustand selection remain authoritative. Tab switching changes visibility rather than mounting/unmounting the AI workflow.
- Native HTML tabs semantics, roving focus, Arrow/Home/End navigation, native scrolling, and existing buttons avoid unapproved component dependencies. shadcn MCP Tabs/Scroll Area were consulted; no installation was necessary.
- Sequence widths represent source duration only. There is no fabricated rendered playhead, trim handle, editable state, save claim, or rerender button.
- Future draft state must be separate from immutable fetched artifacts: base artifact/job ID, schema version, stable cut IDs, revision, dirty state, and undo/redo history. AI revisions must be proposals tied to a base revision with explicit apply/reject and conflict handling.

## Ordered milestones and acceptance criteria

1. **M3.1: Workspace shell (this implementation).** Existing upload, source selection, job recovery/status, storyboard retrieval, native MP4 preview/download remain available. Desktop viewport has no page overflow at 1366×768 and 1920×1080; timeline occupies approximately 35%; docks scroll independently; narrow fallback remains usable. No fake controls or metadata.
2. **Next, for review: backend-driven AI job progress.** Add persisted, safe stage events/fields and timestamps to the worker/status contract. Report actual stage transitions and elapsed time across reloads and failures. No simulated percentages. Existing timestamps may support elapsed running time, but detailed stages need backend changes. Do not begin automatically.
3. **Draft editing/persistence.** Add selected-cut Inspector, reorder/remove, undo/redo, and explicit draft save/restore. Validate project isolation, deterministic history, reload recovery, and stale-base handling. Backend draft save/load and project read APIs are missing.
4. **Manual validation/rendering and accurate seeking.** Add a compatible render-only request, trusted source extraction, bounds/ownership validation, budgets/idempotency, immutable plan/artifact versioning, and frame-based render manifest. Verify output order/ranges, cancelled/failed jobs, and seek mapping at cut boundaries. Keep draft and rendered state separate.
5. **AI revision proposals.** Generate proposals against a specified draft revision. Require explicit apply/reject, surface conflicts, preserve manual edits, and rerender only after validation. Revision endpoints and proposal contracts do not exist yet.

## Verification and limitations

- All 35 frontend tests pass; ESLint and TypeScript typecheck pass. Tests cover existing APIs, file selection, storyboard schema/state/recovery and new tab semantics, keyboard navigation, status labels, and source-duration proportions. No testing dependency was added.
- Browser inspection uses the already completed five-cut job `44c3fa22-3ee4-43ec-a476-3e99172c9af2`, never a newly generated AI job.
- Desktop screenshots and measured document dimensions: 1366×768, 1920×1080, 1440×900, and 1024×768. Narrow fallback: 375×812. Desktop timeline measures approximately 34.95–34.97% of workspace height; Media Pool and AI dock scroll without moving the page.
- Inspector displays real selected media metadata. Brief and source selection survive tab changes. Source-duration widths retain published cut order.
- Native MP4 preview and playback were checked against the existing artifact. The download link exposes the correct 3,140,083-byte video/mp4 blob with an MP4 ftyp header and artifact-based filename. Native file-save completion remains unverified: two download attempts closed the Playwright browser context. The download implementation was preserved. Local file selection and upload/generation request contracts are verified without intentionally sending another upload or AI job.
- Production verification uses `npm run build -- --webpack`; default Turbopack is known to fail in this environment when its CSS worker tries to bind a local port. No build configuration was changed to hide that limitation.
- No timeline editing, exact render seeking, source thumbnails, draft persistence, manual rerender, AI revisions, or detailed stage progress is implemented in M3.1. Live upload success and a fresh AI worker run are not re-exercised in this pass.
