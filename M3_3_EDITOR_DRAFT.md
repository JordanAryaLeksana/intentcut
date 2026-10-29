# M3.2B completion and M3.3 editable timeline

Implemented on `feat/m3-frontend`. Existing unrelated working-tree changes were preserved. No backend changes, migrations, dependency installations, AI inference, commits or pushes were performed in this session.

## M3.2B

`JobTimeline` now explicitly handles absent `job.data` before accessing its status. This preserves published cuts on transient terminal-status refresh errors and uses proper TypeScript narrowing without assertions or casts. The initial `npx tsc --noEmit` passed. Backend-driven processing, polling, recovery and artifact hooks remain in place. The already applied development migration was not repeated.

## Architecture and behavior

- `use-draft-store.ts`: separate, typed Zustand draft state keyed by project. Each draft has immutable base job/artifact identity, stable cut identity, source metadata, published baseline, revision, selected cut, undo and redo snapshots. No persistence middleware or browser draft saving.
- Published array order is authoritative on initialization. Current array position defines draft playback order; original `playback_order` stays as published metadata.
- Selection opens the Inspector without stealing keyboard focus. Native buttons support keyboard selection, move left/right and removal. Boundary moves and invalid selections are no-ops. Removal repairs selection and supports an empty draft. Undo/redo restores both sequence and selection; editing after undo clears redo.
- Same-artifact React Query updates never reset edits. A new result replaces a clean baseline; a dirty draft retains its contents and presents an explicit discard-and-replace action. Project stores/history are isolated. Artifact ingestion additionally checks that the job is still selected.
- Timeline widths use unrounded source duration differences. The displayed total is the sum of current draft cuts, not the rendered MP4 duration. No playhead or exact rendered seek mapping is claimed.
- Inspector displays actual source filename when available, media ID, source range, source duration, published source/playback indices and current playback order. It shares working move/remove controls with the timeline. Trim ranges remain read-only.
- The frontend parser accepts a supplied editorial reason, but the current public backend storyboard intentionally strips prose. Actual jobs therefore show “Not supplied by this storyboard”; no reason is invented.
- Program Monitor retains the published MP4 and labels draft changes as unrendered. Toolbar and timeline report unsaved changes and memory-only storage. Reload discards edits and restores the accepted job/artifacts through existing recovery.

## Files changed in this session

- `frontend/src/features/studio/narrative-timeline.tsx`
- `frontend/src/features/studio/draft-timeline.tsx` (new)
- `frontend/src/features/studio/store/use-draft-store.ts` (new)
- `frontend/src/features/studio/studio-dock.tsx`
- `frontend/src/features/studio/program-monitor.tsx`
- `frontend/src/features/studio/studio-top-bar.tsx`
- `frontend/src/features/studio/studio-shell.tsx`
- `frontend/src/features/studio/studio.css`
- `frontend/src/features/studio/ai-director/storyboard/storyboard-schema.ts`
- `frontend/src/features/studio/__tests__/draft-timeline.test.mjs` (new)
- This report and three browser screenshots.

## Bounded verification

- Initial focused TypeScript check: passed.
- Final ESLint: passed, no warnings/errors.
- Targeted tests: **41 passed**, zero failures/skips. Includes 10 new draft tests plus existing Narrative Timeline, processing timeline, workspace and storyboard parser tests.
- Final production build: `npm run build -- --webpack`; successful compilation, TypeScript and static generation. Webpack used because the prior Turbopack environment could not bind its CSS worker port.
- No backend suites rerun because no backend code changed.

One continuous Playwright smoke session used the existing successful job `44c3fa22-3ee4-43ec-a476-3e99172c9af2`, without submitting a job. Verified five cuts, selection opening Inspector, keyboard move-right, removal, undo/redo, selection retained across a focus refresh, removal to empty, undo from empty, and reload restoring five published cuts. An initial smoke script waited for the download link before loading the on-demand preview and timed out; the same browser session continued after clicking the existing Load MP4 preview control. No browser restart was needed.

Native MP4 playback advanced; duration was 18.833333 seconds, with no media error. The blob URL stayed unchanged through draft removal/undo. The download link had the existing real MP4 filename; native file-save completion was not exercised.

Screenshots reviewed at 1440×900, 1024×768 and 375×812:

- `.playwright-mcp/m33-1440-draft.png`
- `.playwright-mcp/m33-1024-draft.png`
- `.playwright-mcp/m33-375-draft.png`

Desktop document dimensions matched the viewport, with independent panel scrolling. Mobile document width remained 375px, with intentional document scrolling. Screenshots precede the final small cut-text compaction and toolbar status-label adjustment; browser was not rerun for those changes.

Existing upload, media selection, creative-brief submission, job recovery/polling and artifact APIs were left intact. No fresh upload or paid first-cut submission was performed in this session. AI status/recovery behavior is covered by targeted automated tests; live inference remains unverified here. No new AI result was generated to exercise replacement in the browser; draft proposal/refetch behavior is covered by store tests.

## M3.4 requirements (not implemented)

1. Versioned, project-owned draft GET/write contracts with optimistic concurrency (base job/artifact identity and expected draft revision), server validation and conflict handling. Preserve published artifacts and recover drafts after reload.
2. Validate source ownership, immutable source/window references, ordered cuts, allowed operations, duration limits and nonempty render admission. An empty editing draft is safe locally but must not be submitted as a renderable plan.
3. Admit asynchronous renders against an exact saved draft revision, with idempotency, lease-fenced execution, progress and immutable output artifacts.
4. Existing renderer takes prepared extracted windows; it does not accept arbitrary user trim ranges. Define supported window reuse or validated extraction before exposing trim editing.
5. Publish a frame-based render manifest with timebase, ordered cut identity, source mapping and actual rendered frame boundaries for reliable seek synchronization.
6. Define a safe public editorial-reason contract if prose is to be shown. Current backend excludes it deliberately; do not simply remove the sanitization allowlist.
7. Bind rendered output identity to draft revision so the client can truthfully distinguish saved, unsaved, rendered and unrendered states.

No M3.4 implementation has started.
