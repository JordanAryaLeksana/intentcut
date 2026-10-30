# M3.2A — Persistent AI job progress

## Contract and behavior

Job GET retains every existing field and adds optional `progress`. Its stage is one of:

- `preparing_media`: loading, fingerprinting and probing sources.
- `extracting_windows`: extracting and validating prepared windows.
- `understanding_footage`: obtaining validated evidence. `completed_windows` and `total_windows` are provided only here. Valid cache hits count; failed validation does not.
- `selecting_story`: selecting and validating the edit plan.
- `rendering_video`: the real FFmpeg render operation, including output validation.
- `publishing_artifacts`: validating, publishing and atomically registering artifacts.

There is no percentage or ETA. Stage timestamps come from PostgreSQL, not provider responses or the browser. A heartbeat renews ownership but does not change the progress timestamp. No database session stays open across inference or rendering.

`progress` is null for queued, terminal, legacy/uninstrumented, and expired-lease jobs. A newly claimed job remains null until an actual stage starts. Success is still reported only by the existing atomic artifact completion transaction. A failed or expired operation never implies a stage completed. The snapshot describes active work, not an event history or failure-stage record.

## Persistence and concurrency

One nullable `ai_jobs.progress` JSONB column stores the current snapshot; no event table or queue was added. SQL NULL is used for cleared snapshots (`JSONB(none_as_null=True)`). The database constrains non-null values to JSON objects, and the application accepts only an allowlisted schema with paired, bounded window counts and timezone-aware timestamps.

Progress updates lock the project-scoped job row in a short transaction, check running status/current lease token/server-clock expiry, and recheck expiry on the UPDATE. Same-attempt stages and counters cannot move backwards. A rejected lease update stops processing without publishing or marking another owner's job failed. Claim, recovery/requeue and both terminal transitions clear progress. An SQL-computed lease flag gates GET responses, so expired progress is hidden even before recovery runs.

Source preparation now completes before extraction begins; this avoids a false transition back to preparing sources while the API reports extracting windows. Evidence is counted only after `WindowUnderstanding.analyze` returns; that method validates both cached and newly generated evidence. All rendering/publication stage markers are immediately before their actual operation starts.

The existing `worker_cli.py` processing/recovery loop remains inside `with OpenAI(...)`. Its source was not changed by M3.2A. A new regression test asserts that recovery and every loop iteration execute before the client context closes.

## Actual response example

Captured from the real GET endpoint over an isolated PostgreSQL test schema. This is test data, not a live Muse run:

```json
{
  "id": "25d297fd-b31c-4fb5-bb91-58c248b18a60",
  "status": "running",
  "created_at": "2026-10-29T09:33:36.896919Z",
  "updated_at": "2026-10-29T09:33:36.942175Z",
  "started_at": "2026-10-29T09:33:36.933549Z",
  "finished_at": null,
  "attempt_count": 1,
  "error_code": null,
  "progress": {
    "stage": "understanding_footage",
    "stage_started_at": "2026-10-29T09:33:36.939385Z",
    "updated_at": "2026-10-29T09:33:36.939385Z",
    "completed_windows": 1,
    "total_windows": 2
  }
}
```

## Migration and rollout

Existing databases require `scripts/migrations/001_ai_job_progress.sql` before the updated API or workers start. The migration is additive and idempotent; it preserves jobs, artifacts and request payloads. No live/development database migration was applied during this task. Fresh databases receive the column through the existing explicit `Database.initialize_schema()` setup; `create_all` does not migrate an existing table.

Use a libpq-compatible DSN (for example through `PGHOST`, `PGPORT`, `PGDATABASE`, `PGUSER` and `PGPASSFILE`) with:

```sh
psql --single-transaction --file scripts/migrations/001_ai_job_progress.sql
```

Apply it using the application's schema search path, then restart the API/worker processes. Old workers remain compatible with the nullable column and report null progress. Pre-existing jobs are not backfilled. A rolling deployment can therefore temporarily show null progress for running jobs owned by an old worker.

## Files changed by this milestone

- `src/intentcut/backend/jobs/progress.py`: allowlisted progress contract.
- `src/intentcut/backend/jobs/schemas.py`, `routes.py`: additive response field and active-lease visibility gate.
- `src/intentcut/backend/storage/database_models.py`, `database.py`: persistence, fencing, monotonic updates and reset semantics.
- `src/intentcut/backend/ai_processing_adapter.py`: real pipeline boundaries and validated window counts.
- `src/intentcut/backend/ai_worker.py`, `contracts.py`: publishing boundary and explicit lease-loss handling.
- `scripts/migrations/001_ai_job_progress.sql`: explicit migration.
- `tests/unit/backend/test_ai_job_progress.py`, `test_worker_cli.py`: schema, stop-work and OpenAI lifecycle regressions.
- `tests/integration/backend/test_ai_job_progress.py`, `test_uploaded_job_flow.py`: persistence, migration, API, concurrency and real FFmpeg progress regressions.
- `tests/integration/backend/test_ai_job_api.py`: additive API allowlist and current storage imports.
- `tests/integration/backend/test_ai_artifact_repository.py`: repair obsolete storage imports so existing publication/concurrency regressions run.
- This report.

## Verification

- Ruff passes for all changed Python files.
- Full unit suite: 298 passed.
- Relevant PostgreSQL integration suite: 143 passed, including actual FFmpeg extraction/rendering/publication with a fake Muse provider.
- Coverage includes ordered real boundaries; mixed cache hits and new analysis; invalid evidence not counted; wrong project/token; expiry, lock contention, recovery and retries; terminal clearing; response compatibility; idempotent legacy-schema migration; progress-write failure before inference; and existing artifact/worker regressions.
- PostgreSQL and HTTP tests were run outside the sandbox after the sandbox blocked database connectivity and stalled HTTP tests. No live inference or production job was submitted. Tests use isolated schemas in the explicitly configured `_test` database.

Reproduce checks from the repository root:

```sh
uv run pytest tests/unit -q --tb=short
uv run pytest tests/integration/backend/test_ai_job_progress.py tests/integration/backend/test_uploaded_job_flow.py tests/integration/backend/test_ai_job_api.py tests/integration/backend/test_ai_job_repository.py tests/integration/backend/test_ai_worker.py tests/integration/backend/test_ai_artifact_repository.py -q --tb=short
```

## Limits and next review

Progress is a current snapshot, not stage history or an FFmpeg frame counter. Fast stages may start and finish between frontend polls. Old/expired/terminal jobs have no active progress. Detailed per-media preparation/extraction counters, cancellation, percentages, ETA and frontend presentation are outside M3.2A. Progress-persistence failure stops work through the existing safe failure/recovery path rather than continuing with misleading metadata.

No frontend files, dependencies, live schema, worker client lifecycle or unrelated working-tree modifications were changed. Stop for engineering review before M3.2B.
