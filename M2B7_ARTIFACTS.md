# M2B.7: persistent AI artifacts and lease-safe completion

`AIJobWorker` now requires a `ProcessingResult` and an `AIArtifactPublisher` for
normal execution. It keeps its heartbeat running through staging, validation,
publication, and database completion. The processor and the FFmpeg engine keep
their existing interfaces.

## Schema initialization

There is no migration framework in this repository. This milestone adds only the
`ai_job_artifacts` table through the existing explicit, additive initialization:

```sh
uv run intentcut-init-db
```

Run this against the configured database before using the updated worker. It
creates missing tables and does not alter existing tables, delete rows, or backfill
previously succeeded jobs. Repeating initialization preserves existing records.
Do not run schema creation concurrently from multiple application processes.

Each artifact has a UUID primary key, an AI job foreign key with restricted
parent deletion, `video` or `storyboard` kind, a unique relative storage key,
positive byte count, lowercase SHA-256, and a server-generated creation timestamp.
PostgreSQL enforces allowed kinds, safe key shape, checksum shape, and uniqueness
of `(job_id, kind)`. The repository additionally validates that both kinds are
present and that keys match the owning project and artifact UUIDs.

## Wiring the existing real processor

The publisher reuses `LocalMediaStorage`: the same root, copy limits, private
staging, UUID directories, hard-link publication, and cleanup operations as M1B.
Artifact records identify file kinds; the stored basename remains `original`.
No filenames or absolute paths supplied by the processor are persisted as keys.

The real processor now uses uploaded media (M2B.9). Configure the same database,
storage root, and `MODEL_API_KEY` as the API, explicitly enable processing, then:

```sh
AI_PROCESSING_ENABLED=true uv run intentcut-ai-worker --max-jobs 1
```

See [M2B9_UPLOADED_MEDIA.md](M2B9_UPLOADED_MEDIA.md) for the current API and worker
contract. The previous `repository_root` / `evidence_directory` constructor was
removed: cached-evidence requests cannot enter the uploaded-media processor.


`allow_artifact_free_processor=True` exists only for synthetic processor tests
that return `None`. It defaults to false and is rejected for
`RealAIProcessingAdapter`. Any `ProcessingResult`, including one from a fake,
always requires the publisher. The older repository `complete_ai_job` operation
remains for compatibility; production completion uses the artifact transaction.

## Publication and completion

1. Open regular source files with descriptor-relative traversal and `O_NOFOLLOW`
   for every path component. Reject traversal, symlinks, special files, missing
   files, empty files, and oversized inputs.
2. Copy to an independent private staging batch using bounded M1B copies. Compare
   source/staged checksums and detect source changes. Parse a JSON object for the
   storyboard (maximum 8 MiB, also subject to the configured file limit). Inspect
   MP4 container and video metadata using FFprobe and the existing parser, then
   fully decode with FFmpeg and `-xerror`. Storyboard semantics remain validated
   upstream by the existing director and renderer.
3. Hard-link each validated staged file into a fresh artifact UUID directory.
   Existing files or directories are never overwritten or adopted. Verify final
   size and checksum, and fsync data and containing storage directories before
   requesting database completion. Source workspace files remain independent.
4. In a single PostgreSQL transaction, lock the project-scoped job row and check
   running state, token, and current database wall-clock expiry. Insert both
   artifact rows, then recheck expiry in the conditional success update. Commit
   the metadata and status together. A stale worker or competing completion
   cannot register another final pair.
5. On known rollback or rejected ownership, remove only this publication's files.
   Failed cleanup is logged and leaves an orphan; it cannot remove another
   attempt's files. Staging is cleaned on normal exit and exceptions.

The final conditional update is the completion decision while the row lock is
held. Recovery and competing writers cannot change ownership during this
transaction. Filesystem work and FFmpeg never hold the job row lock.

## Uncertain outcomes and limitations

PostgreSQL and local storage do not share a transaction. Once COMMIT is attempted,
exceptions (including connection cleanup after COMMIT) become
`CommitOutcomeUnknown`. The publisher retains files and uses fresh database reads
to reconcile the succeeded job and the complete metadata identity of both
artifacts. A matching committed pair confirms success. A missing result or an
unavailable database does not prove rollback; files remain and the worker does
not mark the job failed. The job ID and artifact IDs are logged for reconciliation.

Process termination, power loss, failed cleanup, and uncertain commits can leave
orphan files. There is no automatic janitor in this milestone. Reconcile against
the primary database after outstanding transactions have ended before deleting
unreferenced files. Recovery retains the existing bounded-attempt policy for jobs
whose transaction actually rolled back. Never delete artifacts solely because a
single query returned no rows during an uncertain commit.

Storage requires Linux/POSIX file descriptors, local hard-link support, and a
trusted private root whose ancestors are controlled by the service operator.
Root and destination symlinks are refused. As with M1B, another process with the
same filesystem privileges must not rename or mutate storage directories while
publication is running. Validation cannot protect against subsequent privileged
file tampering or storage loss. Workspaces are retained for diagnostics. The
storyboard content is preserved as produced and may contain internal source
paths; the database artifact records contain only relative keys.

## Validation and M2B.8

Tests use synthetic local FFmpeg media and isolated PostgreSQL schemas from
`TEST_DATABASE_URL`. No Meta Model API calls are made. Coverage includes validation,
rollback after inserts, constraints, lease expiry while waiting for locks,
competing publications, stale-worker cleanup, heartbeat continuation, and both
committed and uncommitted lost-acknowledgement cases.

```sh
uv run ruff check .
uv run pytest -q
git diff --check
```

For M2B.8, add project-scoped job creation/status and artifact listing/download
endpoints using `list_ai_job_artifacts`. Enforce project authorization and resolve
only stored keys beneath the private root. Serve downloads with explicit content
types (`video/mp4` and `application/json`) and safe filenames; do not expose local
paths or internal storyboard source paths in public responses. Keep completion
and lease ownership exclusively in the worker/repository path.
