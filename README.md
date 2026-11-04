# IntentCut — Your AI Storytelling Director

**From raw footage to a source-grounded first cut—or a short highlight reel—with creator-controlled revisions and real MP4 export.**

IntentCut is a local-first, AI-assisted video editing studio built for the **Meta Global AI Developer Hackathon 2026 — Indie Developer Track**. It offers two connected workflows: **AI First Cut** for arranging one or more clips, and **AI Highlights** for finding useful moments in a longer source. **Meta Muse Spark** provides structured understanding of sampled video moments; the backend validates source-grounded editing decisions and **FFmpeg renders actual downloadable MP4 files**.

**The promise is a useful, inspectable starting edit—not a replacement for a professional editor or a guarantee of a publish-ready film.** Creators can review original timestamps, reorder and remove moments, save drafts, request revisions, manage captions and export the result.

> **Hackathon project** · Built during October 26–November 4, 2026 · Solo developer: [Jordan Arya Leksana](https://github.com/JordanAryaLeksana)
>
> **3-minute demo video:** _Add the public or unlisted, reviewer-accessible demo link before submission._  
> **Source code:** https://github.com/JordanAryaLeksana/intentcut  
> **Submission portal:** https://cerebralvalley.ai/e/meta-ai-developer-hackathon/hackathon/submit

**Jump to:** [Workflow](#see-the-workflow) · [MVP features](#what-works-in-the-mvp) · [Long-footage evidence](#long-footage-validation-november-2026) · [Meta AI](#how-meta-ai-is-used) · [Setup](#quick-start--local-development) · [Worker](#6-run-the-ai-worker) · [Testing](#validation-and-reproducibility) · [Judge's guide](#judges-guide-what-to-look-for) · [Checklist](#hackathon-submission-checklist)

## Why IntentCut?

For travel creators, solo filmmakers, educators, and anyone with a folder of unedited clips, the hardest part often comes **before** fine-grained editing: deciding which moments matter, what order they belong in, and how to turn them into a coherent story.

IntentCut addresses that first-cut bottleneck by combining AI editorial reasoning with deterministic media processing:

- **Understand:** analyze bounded video windows with Muse Spark rather than merely interpreting filenames or a text prompt.
- **Direct:** suggest a storyboard with source-grounded cut selections and a creator-specified narrative intent.
- **Inspect:** show candidate moments, source-relative timestamps, previews and an editable selected sequence.
- **Refine:** reorder/remove moments, persist separate workflow drafts, and accept natural-language changes.
- **Deliver:** render and validate an actual H.264/AAC MP4 with FFmpeg, not a simulated preview.

The project's hackathon theme is **Build for Your World**: reducing the technical and creative friction between capturing footage and telling a story.

## See the workflow

```mermaid
flowchart TD
    A[Create project and add source footage] --> B{Choose workflow}
    B -->|AI First Cut| C[Sample bounded windows from clips]
    B -->|AI Highlights| D[Discover candidate moments in a long source]
    D --> E[Sample bounded candidate windows]
    C --> F[Meta Muse Spark video understanding]
    E --> F
    F --> G[Story Director proposes ordered source windows]
    G --> H[Backend validates EditPlan and source references]
    H --> I[FFmpeg renders and validates a real MP4]
    I --> J[Studio monitor and downloadable output]
    I --> K[AI Highlight Navigator for highlights]
    K --> L[Inspect original previews, reorder and remove moments]
    L --> M[Save Highlights draft and re-render]
    M --> H
    J --> N[Creator-guided revisions]
    N --> H
```

**Key architectural distinction:** local highlight discovery uses bounded visual heuristics to propose *candidate* intervals; Muse Spark supplies semantic understanding and editorial selection. Candidate heuristic scores are **not** model confidence scores. Source timestamps remain authoritative throughout planning and rendering. The Highlights job may produce an initial rendered cut before the creator revises its selected moments in Navigator.

## What works in the MVP

| Capability | What it does | Evidence / scope |
| --- | --- | --- |
| Project and media library | Create projects, upload footage, keep media metadata and readable project slugs | Backend integration-tested; local Studio exercised |
| AI First Cut | Analyze sampled windows and propose an ordered story from one or more clips | Real-MP4 orchestration tests; external Muse provider mocked in automated tests |
| AI Highlights | Discover candidates in one longer source, apply a creative brief and render a highlight reel | Long-footage local run produced a playable ~56-second output; broader reliability not established |
| AI Moment Navigator | Inspect eight discovered candidates, source-relative timestamp markers, an original-footage clip preview and relevance scores | Local browser interaction and a single HTTP/FFprobe preview smoke test |
| Selected Story editor | Reorder/remove selected moments in the right sidebar, then save and re-render | Integrated with the Highlights editing flow; seven selected moments exercised locally |
| Workflow-specific drafts | Persist First Cut and Highlights state independently; recover a saved Highlights selection | Editing API and migration `009_editing_workflows.sql` used in the local demo |
| Program monitor and timeline | Play/download a rendered cut; retain the First Cut timeline when changing workflows | Browser workflow exercised; First Cut and Highlights use different lower workspaces |
| Conversational revisions | Propose and accept changes to a cut, then re-render | Real-MP4 regression tests (see test caveat below) |
| Captions | Edit persisted captions and export a subtitled MP4 | Real FFmpeg burn-in tests; transcription provider is separately configured |
| AI Visuals | Generate/edit visual assets and select a project cover | Persisted API workflow; external provider mocked in automated tests |
| Real export | Publish a downloadable MP4, with probe and decode validation | Real FFmpeg output observed; H.264/AAC on supported render paths |

**Not a claim of:** unrestricted six-hour uploads, guaranteed semantically optimal highlights, instant long-footage previews, full non-linear editing parity, or public multi-user SaaS readiness. See [Limitations](#limitations-and-security).

### Two editing experiences in one Studio

**AI First Cut** is the multi-clip workflow: build a source-grounded storyboard, view its timeline, request revisions and export a real video. **AI Highlights** is designed for a single long source: choose a duration and creative brief, let the job discover/select moments, then inspect the candidate navigator below the main player.

In Highlights, the **AI Moment Navigator** shows the original footage's timestamp ruler, candidate cards, an inspectable source clip and an explanation of the relevance signal. The **Selected Story** sequence is kept in the right sidebar below **Rework your story**, where the creator can move or remove moments, save, and render another version. Original footage is not altered by these choices. First Cut remains a separate workflow rather than being replaced with a highlights-only timeline.

Drafts are **scoped to the editing workflow** so returning to an existing project does not require treating its First Cut and Highlights selections as the same draft. The local demo uses the `workflow=highlights` editing-draft API and migration `009_editing_workflows.sql` for this separation.

## Long-footage validation (November 2026)

A developer-run local demonstration exercised Highlights using **one Tokyo walking-footage MP4 lasting approximately 4 hours 9 minutes and occupying about 6.4 GB**. Eight candidate moments were visible in Navigator; the edited selection contained seven moments, and a playable **roughly 56-second MP4** was produced and shown in Studio. This is evidence for one local run with an existing long media asset, **not** proof that default browser upload settings accept 6.4 GB files or a general six-hour performance guarantee. The workflow's exact Muse provider configuration is not established by this smoke-test record alone.

A separate, no-Muse-cost **preview HTTP smoke test** returned `200`, downloaded approximately **4 MB** of video, and FFprobe measured **7.991 seconds** for an eight-second source interval. That successful request took **11.595 seconds**. An earlier attempt returned `500`, so the record demonstrates a successful individual request, **not** error-free repeated requests or a completed regression suite.

**Preview staging issue and local remediation:** The earlier preview path copied the entire multi-gigabyte source into `.local/media/.tmp` for each request. Repeated/failed requests left approximately **75 GB** of staging files and caused `OSError: [Errno 28] No space left on device`. The local code was changed to use same-filesystem hard-link staging after source verification. In the successful follow-up smoke test, `.tmp` did not grow by another full source copy. The implementation still reads the large source for SHA-256 verification; it is **not** an instant preview cache. File lifecycle, concurrent requests, cancellation cleanup and repeated reliability remain areas to test.

**Do not publish the source footage, temporary media or locally generated private artifacts with the repository.** The local demo uses explicit 10-GiB media admission settings, while AI First Cut retains a separate 512-MiB source budget. These are different paths and the configured limits are not a guarantee of stable multi-gigabyte uploads.

## How Meta AI is used

This is more than a generic chatbot attached to a timeline.

1. **Muse Spark — video understanding:** the worker extracts short, bounded temporal windows from the creator's actual footage. Muse receives those clips and returns structured understanding evidence.
2. **Muse Spark — editorial decision-making:** the Story Director consumes that evidence and the user's creative brief, then selects grounded **window indices**, source media references, and playback order.
3. **Deterministic safety boundary:** the backend—not the model—owns file identities, original timestamps, budgets, EditPlan validation, source fingerprints, and final media rendering. Invalid or invented references are rejected.
4. **Muse Image — optional creative assets:** a separate workflow can generate/edit project visuals and persist cover selection. This does not replace the original video source.
5. **Human-in-the-loop editing:** creators can inspect candidates, review their original source times, reorder/remove selected moments, save drafts and request revisions.

Meta API calls occur in the **background worker**, not in HTTP request handlers. Previewing an already-discovered candidate uses local FFmpeg processing rather than a new Muse call. Automated acceptance tests mock the **external Muse provider boundary**, while exercising real database, orchestration, FFmpeg, artifact persistence and download code. A live-model demo is a separate verification level; mocked tests do not establish real-world editorial quality.

## Architecture and engineering decisions

| Layer | Technology / responsibility |
| --- | --- |
| Web studio | Next.js 16, React 19, TypeScript, Tailwind CSS, React Query, Zustand; cinematic Three.js landing |
| HTTP API | FastAPI and Pydantic: projects, media, jobs, highlights, editing, captions, artifacts |
| Persistence | PostgreSQL 17, SQLAlchemy, Psycopg; durable jobs, media references and workflow-scoped editing drafts |
| AI orchestration | Meta Muse Spark via Meta Model API; bounded, structured and source-grounded inference |
| Media engine | FFmpeg / FFprobe: bounded source-clip previews, temporal extraction, normalization, captions, encoding and validation |
| Worker | Explicit job dispatch, database leases, heartbeat/recovery, bounded processing and artifact publication |
| Optional creative AI | Muse Image for image generation/editing and cover selection; voice transcription is separately configured |

```text
intentcut/
├── frontend/                 # Next.js Studio and landing page
├── src/intentcut/
│   ├── ai/                   # Muse integrations and Story Director
│   ├── backend/              # FastAPI, media, highlights, editing, workers
│   └── media/                # FFmpeg-backed rendering and probes
├── tests/
│   ├── unit/                 # Fast contract and behavior tests
│   └── integration/backend/  # DB, API, media and real-MP4 tests
├── scripts/                  # Development utilities
├── compose.yaml              # Local PostgreSQL services (NOT full-app Docker)
├── pyproject.toml / uv.lock   # Python package and locked dependencies
└── frontend/package-lock.json
```

The architecture separates **model decisions** from **media authority**: Muse can recommend a sequence, but only validated source intervals from registered media can be rendered. The current local-storage preview path validates source identity, uses same-filesystem hard-link staging instead of an additional full-size file copy, and cleans up the response clip after sending. This local staging optimization does **not** establish support for remote object stores or guarantee cleanup after every interrupted request. Published artifacts are checked for integrity and job processing is recoverable within defined limits.

## Quick start — local development

> **Security notice:** IntentCut currently supports trusted, local-first development. The backend does not implement end-user authentication or per-user authorization. Do not expose its API to the public internet, an untrusted LAN, or a public tunnel. UUIDs and project slugs are not access controls.

### Prerequisites

- **Python 3.12.x** and [uv](https://docs.astral.sh/uv/getting-started/installation/)
- **Node.js 24** and npm
- **Docker Engine/Desktop** with Docker Compose v2
- **PostgreSQL 17**, provided through Docker Compose
- **FFmpeg and FFprobe**, with H.264 (`libx264`) and AAC encoding support
- **Meta Model API key**, required only for live Muse-powered processing

The primary validated environment is Ubuntu Linux with Python 3.12, Node.js 24, PostgreSQL 17, and FFmpeg 8.0.1.

### 1. Clone and configure

```bash
git clone https://github.com/JordanAryaLeksana/intentcut.git
cd intentcut
cp .env.example .env
```

Edit `.env` locally. The following is the **current large-footage demo configuration**, with credential placeholders. It is not the package's default configuration:

```dotenv
# Replace placeholders locally; never commit real credentials.
# Use the same URL-safe password in all three database settings.
POSTGRES_PASSWORD=CHANGE_ME
DATABASE_URL=postgresql+psycopg://intentcut:CHANGE_ME@127.0.0.1:5432/intentcut
TEST_DATABASE_URL=postgresql+psycopg://intentcut:CHANGE_ME@127.0.0.1:5433/intentcut_test
MEDIA_ROOT=.local/media
MODEL_API_KEY=your_actual_meta_api_key

# AI access / paid processing
AI_JOBS_LOCAL_ENABLED=false
AI_PROCESSING_ENABLED=false
AI_JOBS_BROWSER_ENABLED=true
CORS_ORIGINS='["http://localhost:3001","http://127.0.0.1:3000","http://127.0.0.1:3001","http://127.0.0.1:3021"]'

# Local demo: large-footage admission
MAX_FILE_BYTES=10737418240
MAX_REQUEST_BYTES=11811160064
HIGHLIGHT_MAX_SOURCE_BYTES=10737418240

# AI First Cut: source / remote budgets
AI_MAX_SOURCE_BYTES=536870912
AI_MAX_REMOTE_TOTAL_BYTES=104857600
AI_STORY_MAX_OUTPUT_TOKENS=4000

# AI First Cut: temporal budgets
AI_MAX_MEDIA=10
AI_MAX_WINDOWS=30
AI_MAX_INFERENCE_REQUESTS=31

# Optional voice transcription
VOICE_TRANSCRIPTION_ENABLED=true
VOICE_MAX_DURATION_SECONDS=120
VOICE_MAX_JOBS_PER_PROJECT=3
VOICE_TIMEOUT_SECONDS=180
```

| Setting group | Meaning |
| --- | --- |
| Database + `MEDIA_ROOT` | Use the same database and local media root for API **and** worker; test DB stays separate |
| `AI_JOBS_*` | Browser access and local AI-job admission are separate switches; `AI_JOBS_LOCAL_ENABLED=false` can block the local job endpoints even with browser access enabled |
| `AI_PROCESSING_ENABLED` + `MODEL_API_KEY` | Paid Muse processing remains disabled until **explicitly** enabled with a valid key |
| Media / Highlights caps | Up to **10 GiB** per file and Highlights source; **11 GiB** request cap (configuration limits, not a throughput guarantee) |
| First Cut budgets | **512 MiB** source, **100 MiB** total remote inputs, 10 media, 30 windows, 31 inference requests, 4,000 story output tokens |
| Voice | Transcription enabled with 120-second duration, 3 jobs/project and 180-second timeout; provider configuration/costs depend on the voice path |

**For a trusted, local browser-based AI demo only:** set `AI_JOBS_LOCAL_ENABLED=true`, keep `AI_JOBS_BROWSER_ENABLED=true`, and set `AI_PROCESSING_ENABLED=true` **only if** you intend to run a paid Muse job. Add the actual frontend origin to `CORS_ORIGINS` if different (e.g. `http://localhost:3000` is **not** listed above). Restart the API and worker after `.env` changes. Large-upload limits require enough free disk and time; a configured 10-GiB cap does not prove every 10-GiB upload works.

**Never commit `.env`, expose API credentials in frontend variables, or include secrets in demo recordings.**

### 2. Start PostgreSQL and install Python dependencies

```bash
docker compose up -d postgres
docker compose ps

uv python install 3.12.15
uv sync --frozen
```

Initialize the database:

```bash
uv run --env-file .env intentcut-init-db
```

The PostgreSQL application service is published on `127.0.0.1:5432`.

Docker Compose starts the database service, not the complete IntentCut application.

**Important:** Database initialization creates missing tables but does not migrate existing tables to newer schemas.

### 3. Database migrations for existing installations

If you are upgrading an existing IntentCut database, inspect the SQL migrations under:

```text
scripts/migrations/
```

Migration files are versioned and should be applied in the required sequence, based on the current database schema.

For example, migration `007_project_slugs.sql` adds and backfills readable project slugs while retaining existing project UUIDs. **Migration `009_editing_workflows.sql` scopes edit drafts to `(project_id, workflow)`**, allowing First Cut and Highlights edits to coexist. An existing installation that skips 009 can fail to reopen or save a Highlights draft even if its rendered MP4 already exists.

Before applying any migration:

1. Back up the application database.
2. Review the migration SQL and confirm the target database.
3. Stop concurrent writes.
4. Execute the applicable migration transactionally.
5. Verify the resulting schema and API behavior.

The following example applies **migration 007 only**, assuming earlier migrations have already been applied and the PostgreSQL container is configured for the `intentcut` application database.

Create a backup:

```bash
mkdir -p .local-backups
chmod 700 .local-backups

docker compose exec -T postgres \
  sh -c 'exec pg_dump -U "$POSTGRES_USER" -d "$POSTGRES_DB" -Fc' \
  > .local-backups/intentcut-before-007.dump
```

Verify the backup archive:

```bash
docker compose exec -T postgres pg_restore -l \
  < .local-backups/intentcut-before-007.dump
```

Apply the migration:

```bash
{
  printf 'BEGIN;\n'
  cat scripts/migrations/007_project_slugs.sql
  printf '\nCOMMIT;\n'
} | docker compose exec -T postgres \
  sh -c 'exec psql -X -v ON_ERROR_STOP=1 -U "$POSTGRES_USER" -d "$POSTGRES_DB"'
```

After a successful commit, verify the application endpoint:

```bash
curl -i http://127.0.0.1:8000/projects
```

Run this HTTP check after starting the API in the next step. A successful request should return HTTP `200`.

Do not delete existing PostgreSQL volumes to resolve schema mismatches.

For an installation whose earlier migrations are already applied, **inspect** `scripts/migrations/009_editing_workflows.sql`, back up the database, stop concurrent writes, and run that file against the correct database. The supplied 009 script contains its own transaction; do not wrap it in a second ad-hoc transaction. Example for the `postgres` Compose service:

```bash
docker compose exec -T postgres \
  sh -c 'exec psql -X -v ON_ERROR_STOP=1 -U "$POSTGRES_USER" -d "$POSTGRES_DB"' \
  < scripts/migrations/009_editing_workflows.sql
```

Then reopen the project and verify that saving and reloading a Highlights draft does not overwrite the First Cut draft. Run each migration **only after verifying which migrations your existing database actually needs**.

### 4. Start the backend API

From the repository root:

```bash
uv run --env-file .env uvicorn intentcut.backend.app:create_app \
  --factory \
  --host 127.0.0.1 \
  --port 8000 \
  --no-proxy-headers
```

The API will be accessible at:

- API documentation: `http://127.0.0.1:8000/docs`
- Projects endpoint: `http://127.0.0.1:8000/projects`

If port `8000` is already occupied, use another available loopback port (the long-footage local smoke test used `8012`) and update the frontend API URL accordingly.

**Keep the backend bound to `127.0.0.1`.**

### 5. Start the frontend Studio

Create `frontend/.env.local`:

```dotenv
NEXT_PUBLIC_API_BASE_URL=http://127.0.0.1:8000
```

Then run:

```bash
cd frontend
npm ci
npm run dev
```

Open `http://127.0.0.1:3000`.

Create a project, upload authorized footage, and enter the editing Studio.

If port `3000` is occupied, start Next.js on another port:

```bash
npm run dev -- --hostname 127.0.0.1 --port 3001
```

When changing the frontend port, add the corresponding origin to `CORS_ORIGINS` and restart the backend. Restart the frontend after changing its API configuration.

### 6. Run the AI worker

**API ≠ worker:** FastAPI queues and reports jobs; the separate worker processes them. Start PostgreSQL + API, then the frontend, and run the worker **from the repository root** in another terminal. API and worker must use the **same `.env`, PostgreSQL database and `MEDIA_ROOT`**.

**Before paid AI processing:** replace `MODEL_API_KEY`, enable `AI_JOBS_LOCAL_ENABLED=true` for trusted loopback browser job access, and opt in with `AI_PROCESSING_ENABLED=true`. These differ from the disabled values in the demo `.env` template above. Restart the API after changing the flags. Create the AI First Cut / Highlights job in Studio *before* invoking a one-shot worker.

#### AI worker command reference

> **Choose one command per worker session**; the examples are alternatives, **not** a script to run top to bottom. The exact options depend on your checked-out code: check `--help` first.

| Command (repository root) | Purpose |
| --- | --- |
| `uv run --env-file .env intentcut-ai-worker --help` | List available flags and accepted values |
| `uv run --env-file .env intentcut-ai-worker --max-jobs 1` | Process at most **one queued job**; recommended for a controlled demo |
| `uv run --env-file .env intentcut-ai-worker --max-jobs 2` | Process up to **two jobs** in one invocation (not two Muse calls) |
| `uv run --env-file .env intentcut-ai-worker --manual-only --max-jobs 1` | Process only the manual-job category |
| `uv run --env-file .env intentcut-ai-worker --voice-only --max-jobs 1` | Process only voice/transcription jobs |
| `uv run --env-file .env intentcut-ai-worker --captions-only --max-jobs 1` | Process only caption-related jobs |
| `uv run --env-file .env intentcut-ai-worker --image-only --max-jobs 1` | Process only image-generation/editing jobs |
| `uv run --env-file .env intentcut-ai-worker --continuous --poll-seconds 3` | Keep polling for jobs every 3 seconds; **use only when ongoing processing and costs are intended** |

**Flag cheat sheet:** `--max-jobs N` controls jobs handled in an invocation (not model requests per job); `--*-only` filters are mutually exclusive; `--continuous` keeps polling; `--poll-seconds N` sets the polling interval. Some older notes mention `--max-attempts 1`: **only use that flag if your current `--help` actually lists it**, and do not confuse retry/attempt controls with `--max-jobs`.

**First Cut / Highlights:** use the **unfiltered** one-job worker unless you have verified a filter that includes the queued job type. Each AI job can make multiple Muse calls. Avoid continuous mode or repeated runs unless you accept possible provider charges.

**Check the result:** watch worker logs, then confirm Studio shows a successful job, storyboard/selected moments and playable downloadable MP4. If a job stays `queued`, check the three enablement flags, DB/media root, worker logs and any `--*-only` filter. If it fails, inspect the error **before** retrying.

**No new Muse call required:** viewing an existing Highlight Navigator candidate uses local FFmpeg preview; running `intentcut-render` below tests rendering separately from Meta inference.

### 7. Verify deterministic video rendering

Without a Meta API key, the FFmpeg-based renderer can be exercised independently:

```bash
uv run intentcut-render \
  path/to/first.mp4 \
  path/to/second.mp4 \
  -o output.mp4
```

Provide existing, supported input media and a valid output path.

This verifies deterministic media rendering, **not Muse Spark video understanding or editorial reasoning**.

---

## Operating system and device guidance

IntentCut primarily targets local development and desktop-browser editing. Cross-platform compatibility should be distinguished from actual end-to-end validation.

| Environment | Guidance | Validation |
| --- | --- | --- |
| Ubuntu/Linux | Python, uv, FFmpeg, Node.js, and Docker Compose | Primary tested environment |
| Windows 11 | Use WSL2 Ubuntu with Docker Desktop integration | Recommended; not separately E2E-certified |
| macOS | Install dependencies using Homebrew or equivalent | Expected compatibility; requires verification |
| Native Windows | Prefer WSL2 for consistent shell, path, and FFmpeg behavior | Not validated |
| Mobile/tablet browsers | Responsive interface available; local-only API networking limits remote-device access | Viewport tests do not establish device E2E |

The provided `compose.yaml` runs PostgreSQL services. It does not provide a universal one-command deployment of the complete application.

### Troubleshooting

| Problem | Recommended check |
| --- | --- |
| API returns `database_unavailable` | Confirm database connection, inspect SQLAlchemy logs, and verify migrations |
| `column projects.slug does not exist` | Review and apply migration 007 after a verified backup |
| Browser returns CORS errors | Check the exact frontend origin in `CORS_ORIGINS` and restart the API |
| Studio cannot connect to the API | Verify Uvicorn port and `NEXT_PUBLIC_API_BASE_URL` |
| AI job remains queued | Check worker execution, feature flags, and database configuration |
| Upload returns HTTP 413 | Inspect upload and request-size limits |
| FFmpeg rendering fails | Check codecs, filters, source format, and available disk space |
| Navigator shows “no Highlight discovery report” | Confirm the active project/workflow; switch to First Cut for projects that have no Highlights report |
| Highlights draft cannot be reopened | Check workflow-scoped draft state and whether migration 009 was applied |
| Preview returns HTTP `500` or `No space left on device` | Inspect the backend traceback, `df -h`, and `du -sh .local/media/.tmp`; an older preview implementation copied large sources into staging |
| Long-source preview seems slow | Source SHA-256 verification and FFmpeg extraction can take seconds; a single successful request took ~11.6 s on the local demo |

Useful diagnostics:

```bash
docker compose ps
ffmpeg -version
ffprobe -version
ffmpeg -h filter=scale
ffmpeg -encoders
```

---

## Validation and reproducibility

### Backend tests

Start the dedicated test database:

```bash
docker compose --profile test up -d postgres-test
```

Run the automated tests:

```bash
uv run --env-file .env pytest tests/unit/ -q
uv run --env-file .env pytest tests/integration/backend/ -q
uv run ruff check .
uv run ruff format --check .
```

The test database must be isolated from the application database. Never run integration tests against a production database.

### Frontend validation

```bash
cd frontend

npm ci
npm run build

npm run test:api
npm run test:media
npm run test:storyboard
npm run test:timeline
npm run test:highlights
npm run test:highlights-nav
```

### Reported verification results

On November 3, 2026, the final-submission audit reported:

- **479 passing unit tests**
- **264 passing backend integration tests**
- Successful Next.js production build
- Real FFmpeg-based MP4 generation and validation
- Browser-to-worker workflows tested using a deterministic mock Muse provider

These are **historical, local developer-reported results for the November 3 audit**, not a fresh test run on the subsequently edited `test/large-footage-demo` branch or a public CI certification. Re-run the suite on the final commit before claiming current green status.

**Mocked Muse provider tests and live Muse inference are separate verification levels.** Automated tests validate orchestration, data persistence, and media rendering without establishing the semantic quality of real-model editorial decisions.

Actual live inference outcomes should be documented separately after verification.

### Latest focused manual smoke test

On November 5, 2026, the Highlights preview endpoint was exercised against one existing long-footage project after staging cleanup and a local-storage fix. The observed successful attempt returned HTTP `200`, produced a playable MP4 with **7.991-second duration** (FFprobe) and completed in **11.595 seconds**. The `.tmp` directory did not increase by the size of the original ~6.4 GB video. An earlier attempt returned `500`; a complete repeated-request, cancellation and cross-project regression run has **not** been reported.

To repeat a preview check without new Muse inference, use an **existing project and media asset** and an allowed interval; the API must already be running:

```bash
# Set project/media IDs and a valid interval for your own local project.
PROJECT_ID="replace-with-project-uuid"
MEDIA_ID="replace-with-media-uuid"
START=0
END=8
API_URL="http://127.0.0.1:8000"

curl --fail --show-error \
  -o /tmp/intentcut-highlight-preview.mp4 \
  -w 'HTTP %{http_code} | Duration %{time_total}s\n' \
  "$API_URL/projects/$PROJECT_ID/ai-jobs/highlights/preview?media_id=$MEDIA_ID&start_seconds=$START&end_seconds=$END"

ffprobe -v error -show_entries format=duration \
  -of default=noprint_wrappers=1 \
  /tmp/intentcut-highlight-preview.mp4

du -sh .local/media/.tmp
```

Choose a valid interval for the target asset, and compare staging size before and after. Do not assume that one HTTP `200` establishes performance, security or reliability under concurrent load.

## Limitations and security

- **Local-first, not public SaaS:** project/media routes do not implement user authentication or authorization; AI routes use a configurable local-only guard. Do not expose this service publicly or treat loopback protection as user authentication.
- **Ingestion limits:** the **local demo overrides** set `MAX_FILE_BYTES=10 GiB`, `MAX_REQUEST_BYTES=11 GiB` and `HIGHLIGHT_MAX_SOURCE_BYTES=10 GiB` (values shown in the `.env` tutorial). These are admission caps, **not a claim of validated 10-GiB browser uploads**. An earlier default was 128 MiB/file and 512 MiB/request; deployments must check their own settings.
- **Long footage:** one ~4h9m / ~6.4 GB single-source workflow was exercised locally and produced a ~56-second MP4. This does **not** certify six-hour uploads, every codec/container, repeated long-video processing or production-scale rendering.
- **Bounded inference:** the **current demo `.env`** configures up to 10 media, 30 analyzed windows and 31 inference requests for AI First Cut, with 512-MiB source and 100-MiB remote-input budgets. These are ceilings, not guaranteed usage counts. Long-form discovery chooses candidates; it does not semantically analyze every frame in a six-hour recording.
- **AI quality:** heuristic candidate scores measure inexpensive image properties; live semantic selection is model-dependent and may require creator judgment. Provider calls require an active API key and may incur charges.
- **Media constraints and previews:** FFmpeg software encoding, intermediate files, full validation and repeated full-source hashing require CPU, I/O and free disk space. Previous staging copies exhausted local disk; same-filesystem hard-link staging mitigates full-size copy amplification but not all crash/cancellation or concurrency scenarios. Unsupported formats and invalid durations can fail validation.
- **Editing scope:** IntentCut is an explainable first-cut copilot. It does not aim to replace a professional non-linear editing suite with arbitrary effects, collaborative multi-user access, or guaranteed production-quality edits.
- **Footage rights:** upload only footage you own or are authorized to reuse. A publicly viewable video is not automatically licensed for editing, redistribution, or a hackathon demonstration.

## Technical implementation and verification

IntentCut's main capabilities are implemented and verifiable through the application source code and automated tests:

- **Media ingestion and AI orchestration:** Project creation, footage uploads, temporal video analysis with Muse Spark, AI job processing, and validated edit plans.
- **Video rendering:** FFmpeg-based MP4 generation, media probing, output validation, and end-to-end rendering tests.
- **AI-assisted editing:** Persistent edit drafts, storyboard inspection, natural-language revision proposals, and re-rendering.
- **Creative tools:** Editable captions, subtitled video exports, Muse Image-generated visuals, and project cover selection.
- **Long-form highlights:** Candidate discovery, a separate Navigator beneath the Studio player, source clip previews, Selected Story controls in the sidebar, and workflow-scoped draft persistence.
- **Engineering verification:** Unit tests, backend integration tests, frontend component tests, and real MP4 end-to-end tests.

For further inspection, see the `src/`, `frontend/src/`, `scripts/`, and `tests/` directories, along with [Engineering conventions](AGENTS.md).

The source code and current tests are authoritative for implemented behavior.

## Judge's guide: what to look for

The intended demonstration is a **working video-editing loop**, not a simulated UI or a promise of fully autonomous editing. The original video and creator intent flow into grounded source timestamps and real MP4 output.

| Area | Inspect in IntentCut |
| --- | --- |
| User impact | A useful first cut from multiple clips, or a concise edit from a much longer video |
| Meta AI integration | Muse Spark video-window understanding and source-grounded editorial choices; optional Muse Image visuals |
| Technical execution | Persistent jobs and drafts, validated EditPlans, FFmpeg rendering, artifact checks and bounded preview extraction |
| Creator control | First Cut timeline, Highlights moment inspection, selected-story reorder/remove, revision and download |
| Evidence integrity | Distinguish mocked-provider acceptance tests, developer-run local demos and verified live-provider traces |

**Built by [Jordan Arya Leksana](https://github.com/JordanAryaLeksana) · Meta Global AI Developer Hackathon 2026 · Indie Developer Track**

*IntentCut: AI proposes the story. The creator directs it. FFmpeg makes it real.*
