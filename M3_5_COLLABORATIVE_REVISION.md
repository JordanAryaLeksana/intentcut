# M3.5 — Human-approved AI sequence revisions

Implemented on `feat/m3-frontend`, preserving the existing dirty worktree. No commits, pushes, dependency installations or paid inference requests. M3.6 has not started.

## API contracts

The persistent draft is the existing single project-owned head (`edit_drafts.project_id` is its identity). Thus `draft_id` equals the project UUID; its monotonically increasing revision identifies the exact saved sequence. There is no second competing draft system.

All endpoints are under `/projects/{project_id}/edit-draft/proposals`, protected by the existing opt-in loopback/browser-origin boundary and project scoping.

| Method | Suffix | Behavior |
| --- | --- | --- |
| POST | empty | `{request_id: UUID, draft_revision: integer, instruction: string}` → 202 `{id, status_url}` |
| GET | empty | `{items: [proposal...]}`, newest 50 requests |
| GET | `/{id}` | One persisted proposal and its authoritative job status |
| POST | `/{id}/accept` | `{expected_revision: integer}` → `{proposal, draft}`; 409 on conflict |
| POST | `/{id}/reject` | Empty body → `{proposal, draft: null}`; preserves draft |

A proposal response explicitly allowlists: ID, draft/project ID, exact base job/artifact/revision, creator instruction, proposal state, job status, safe error code, creation/finish timestamps, active safe progress, current-at-request sequence, proposed sequence, validated explanation/reasons, server-computed removed IDs/reordering flag, and applied revision.

`request_id` is also the job ID and deduplicates unchanged submission retries. A conflicting use of an existing identifier is rejected. Admission checks the current saved revision twice, including under the same project-row lock used by M3.4 saves. At most one queued/running revision request per project is admitted. Empty drafts and whitespace-only instructions are rejected; instructions are limited to 1,000 characters. No inference runs in the request handler.

## Genuine Muse integration

`MuseClient.revise` makes one text-only `responses.create` request to **muse-spark-1.3**, using the existing configured client, `store=False`, low reasoning effort and strict JSON Schema output. It never calls file upload, video understanding or Story Director selection for a sequence revision.

The input contains the exact saved current sequence, authorized source IDs/ranges/window references, published cut metadata, a context-availability note and the creator instruction. Only public source/order/range metadata is used; private visual evidence, hidden first-cut prose, source files, storage paths, fingerprints and credentials are not sent as revision context. This means requests requiring visual knowledge absent from that context must be declined rather than invented.

Structured output is either:

- `proposed`: a nonempty ordered unique subset of the **current saved cuts**, explanation and one reason per retained cut in matching order.
- `unsupported`: no edits, with a bounded explanation. The job fails with safe code `unsupported_revision`; UI explains the supported limits.

The server rejects fabricated IDs, duplicates, adding back previously removed cuts, empty/no-op sequences, extra unsupported fields, invalid structured output and unsafe editorial prose. Model output cannot supply timestamps, paths, media URLs, arbitrary operations or a replacement EditPlan. Bounded prose is rendered as plain escaped text; strings resembling private paths, credentials, URLs or control characters are rejected. Raw provider responses and exception diagnostics are neither persisted nor exposed. Unsupported semantic instructions are handled by the structured prompt/outcome; live instruction fidelity remains unverified without an approved provider call.

The diff summary is calculated by the server independently of the model explanation. The proposed order never mutates the saved draft automatically.

## Persistence, ownership and lifecycle

One additive `revision_proposals` table stores job ID, lifecycle state, validated result JSON and accepted revision. The existing `ai_jobs` row stores the immutable request snapshot and authoritative queued/running/succeeded/failed processing lifecycle.

Proposal states are pending, accepted, rejected and stale; failed is safely derived from the persisted job failure. Pending includes both processing and ready-for-review, distinguished by job status and result availability. A newer head revision makes an unaccepted proposal stale across refreshes; an attempted stale acceptance also persists that state.

`RevisionProcessor` is dispatched by the existing worker for `pipeline_version: revision_v1`. It checks that the saved head is still current before inference, persists the real `revising_sequence` stage immediately before the provider call, validates the reply and returns an explicit `ProposalResult`. The worker publishes the validated result and terminal job success in a single short lease-fenced transaction. Checks include job/project identity, running status, token ownership and database wall-clock expiry, with a final conditional update after flushing the result. Heartbeat/recovery behavior is reused. There are no fake artifacts or artifact-free production processing exceptions.

Acceptance locks the project head and job, requires a succeeded pending proposal and exact base revision, revalidates the sequence, increments the saved head revision and records acceptance atomically. Concurrent manual saves and proposal acceptance cannot both win against the same expected revision. Repeated acceptance is idempotent while that accepted head is still current. If a later concurrent save has advanced the head before the response is read, acceptance returns a conflict rather than sending unrelated edits to the client.

Rejection leaves the draft untouched. Queued/running rejection revokes the job lease and marks it failed with a safe cancellation code, preventing late result publication. An already in-flight provider call cannot be unbilled or forcibly undone. Accepted proposals cannot subsequently be rejected.

Normal worker processing stays inside the OpenAI client context. `--manual-only` still constructs no Muse/OpenAI client and never claims revision jobs. Accepted versions use the unchanged M3.4 manual render pipeline, with immutable revision snapshots and measured frame manifests; acceptance itself never changes an existing MP4.

## Frontend review workflow

The AI Director now contains a real revision instruction form and persistent proposal history. Existing first-cut controls, uploads, media selection, Inspector, source metadata, MP4 preview and version switching are retained.

Submission requires a nonempty saved draft matching local edits. Queued waiting, real running stage, ready review, rejection, failure, unsupported requests, stale proposals and acceptance are distinguished. React Query polls active requests every two seconds and stops on terminal job states; focus and explicit refresh recover persisted requests. Failed refreshes are labeled as potentially stale cached data. Mutations are not automatically retried; uncertain unchanged submissions retain their request identifier.

Each review shows the creator instruction, exact base revision, current-at-request versus proposed cut references/order, server-computed removals/reordering and bounded AI editorial reasoning. Accept and Reject are explicit native keyboard-accessible actions. Acceptance is disabled if the current local/saved sequence no longer aligns with the proposal. Backend 409 conflicts retain local edits and offer explicit reload.

Accepted cuts become one undoable local edit and a confirmed saved revision. Selection is retained if its cut survives; removed selections clear safely. If newer local edits were made while acceptance was in flight, they are preserved and the new server revision is tracked separately, leaving the working draft unsaved. Undo after acceptance is a local unsaved edit; redo can match the saved accepted sequence again. An accepted decision recovered after an uncertain response offers an explicit reload instead of silently replacing local edits.

The timeline and Inspector read the same draft store. The original/current rendered MP4 remains separate. The existing Save Draft and Render Updated Cut actions provide all persistence/rendering; no automatic render or misleading updated-video claim was added.

## Migration and development readiness

`scripts/migrations/003_revision_proposals.sql` is additive and idempotent. It was applied transactionally twice to the verified **local development** PostgreSQL database, after a verified custom-format backup and confirmation that no jobs were queued/running. Full-row fingerprints preserved 5 projects, 18 assets, 13 jobs, 10 artifacts and the existing saved draft head.

Backup: `.local/backups/m35-20261029T173808Z/intentcut.dump`, 18,256 bytes, SHA-256 `4ed1f9bcb671d1b2499595e911715d80b51efaaabc44c9ac871dc0f7559005fb`. Backup permissions are restricted; both archive listing and full extraction were checked. Verification/runtime records are in that backup directory. API and the existing continuous worker were restarted with their previous options. Other environments must apply migration 003 explicitly; startup does not migrate schemas.

A final read-only runtime check confirmed API availability, worker liveness, **zero proposal rows**, the original 13 jobs, and the unchanged development saved revision 1/order `[6,2,4,8]`. No paid requests were submitted.

## Verification

- Final scoped Ruff: passed for all changed backend source and tests.
- Relevant backend regression run: **153 passed** in 44.85 seconds.
- Separate unit progress file: **15 passed** in 0.10 seconds. It was run separately because its existing basename duplicates the integration progress module; the first combined collection attempt stopped before executing tests. Final relevant backend total: **168 passed**, no failures/skips.
- Coverage includes strict text-only Muse transport, invalid/unsupported/fabricated output, safe prose, provider failures, genuine reorder/removal proposals, rejection, idempotent submission/acceptance, wrong-project access, stale/concurrent acceptance, pre-inference stale detection, expired lease fencing/recovery, cancellation, migration creation/idempotency, OpenAI lifecycle, manual-only provider isolation, first-cut compatibility, saved draft/manual rendering and existing progress/worker/artifact regressions.
- Accepted proposal integration uses mocked inference followed by actual PostgreSQL state transitions and real FFmpeg generation/validation of the accepted saved revision. No paid provider is used in tests.
- Frontend: **72 tests passed**, zero failures/skips. Seven new revision tests cover comparison/actions, states, undo/redo acceptance, newer-edit protection, project isolation, recovery/polling, invalid responses and exact mutation contracts. Existing editing/API/media/progress regressions pass.
- Frontend ESLint and TypeScript: passed.
- One production build (`npm run build -- --webpack`): passed compilation, TypeScript and static generation. No repeated production build was needed.

One continuous Playwright smoke pass used **intercepted proposal/decision responses**, not a live provider or production proposal records. It verified queued → running → ready, rejection preserving four cuts, acceptance changing four to three cuts, undo restoring four, redo, and reload recovery of the accepted fixture. It explicitly blocked other live mutations, removed all intercepts afterward and restored the unchanged real four-cut saved draft. Four fixture POSTs (two requests, reject, accept) never reached the backend.

Screenshots reviewed: `.playwright-mcp/m35-fixture-1440.png`, `m35-fixture-1024.png`, `m35-fixture-375.png`. Desktop document dimensions matched 1440×900 and 1024×768; mobile width remained 375px with intentional document scrolling. The dock scrolls independently. The development console contained earlier rollout-time 404/HMR hydration messages while old API/HTML were still loaded; the smoke's fresh reloads completed successfully. No live browser inference/acceptance or new native file-save completion was claimed.

## Changed files

New:

- `src/intentcut/ai/revision.py`
- `src/intentcut/backend/editing/revisions.py`
- `src/intentcut/backend/editing/revision_routes.py`
- `scripts/migrations/003_revision_proposals.sql`
- `tests/unit/backend/test_revision_provider.py`
- `tests/integration/backend/test_revision_proposals.py`
- `frontend/src/lib/api/revisions.ts`
- `frontend/src/features/studio/ai-director/revision-chat.tsx`
- `frontend/src/features/studio/__tests__/revision-chat.test.mjs`
- This report and three fixture smoke screenshots.

Extended:

- `src/intentcut/ai/muse.py`
- `src/intentcut/backend/{app,ai_worker,contracts,worker_cli}.py`
- `src/intentcut/backend/jobs/progress.py`
- `src/intentcut/backend/storage/database_models.py`
- `frontend/src/lib/api/{contracts,job-progress}.ts`
- `frontend/src/features/studio/ai-director/connected-director.tsx`
- `frontend/src/features/studio/ai-director/processing-state.ts`
- `frontend/src/features/studio/store/use-draft-store.ts`
- `frontend/src/features/studio/studio.css`

## One controlled live acceptance test — requires explicit approval first

**Not executed.** Obtain explicit approval for exactly one paid Muse revision request before starting this procedure.

1. Confirm migration 003, the API and the updated worker are running. Use the normal worker with its default `--max-attempts 1`; do not enable automatic inference retries. The established client uses `max_retries=0`.
2. Open the existing project, inspect the sequence and save any manual edits. Record the saved revision and current rendered version. Current verified development head is revision 1/order `[6,2,4,8]`, but recheck it before testing.
3. In AI Story Director, submit once: **“Move the last cut to the first position. Keep all other cuts in their existing relative order and remove nothing.”** Against the verified head this should propose `[8,6,2,4]`.
4. Wait for a truthful queued/running/ready transition. If submission is uncertain, use Refresh proposals and inspect the persisted request; do not create another request with a new identifier. Review the exact order, unchanged source references, base revision, server diff and AI explanation. Provider compatibility/structured-output fidelity is what this test still needs to establish.
5. Before acceptance, confirm the saved draft and current MP4 remain unchanged. Accept once; verify a new saved revision, updated timeline/Inspector and an explicit unrendered state. Reload and confirm accepted persistence. A manual save advancing the revision before acceptance should instead produce a conflict.
6. Use **Render Updated Cut** for the accepted saved revision. This is manual FFmpeg processing, not another Muse call. Verify terminal success, manifest/source order, version-specific playback/download, and that the older rendered version remains selectable and unchanged.

If the provider fails or returns unsupported/invalid output, retain the original draft and review the safe error before authorizing another paid attempt. Rejecting a ready proposal is the alternative non-mutating decision; do not request another proposal merely to exercise rejection, since it is covered by automated tests.

## Remaining limits

No live Muse call has been approved or made, so end-to-end provider behavior remains unverified. Revision context has authorized source/order/range data but not private visual understanding; semantically grounded content revisions needing that evidence are outside this version. Only reorder/remove of currently retained cuts is supported. No arbitrary trim, footage generation, music, transitions, keyframes, generic agents or autonomous application/rendering.

History shows the latest 50 requests; older proposal IDs remain individually retrievable. This is the existing local access model, not production multi-user authentication. Proposal/draft state persists; local undo history and unsaved edits remain memory-only. Inference already in flight can finish after cancellation, but its rejected result cannot be published or applied. SDK/worker retry policy must remain bounded to control live costs.

Stopped before M3.6 hardening/submission work.
