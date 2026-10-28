# IntentCut — Your AI Storytelling Director

IntentCut combines a reusable local media engine with a FastAPI backend for
project uploads, bounded Muse first-cut processing, and persistent MP4/storyboard
artifacts. See the [M2B.9 guide](M2B9_UPLOADED_MEDIA.md) for the current upload →
queued job → worker → download workflow and its local-only access requirements.

## Requirements and setup

Ubuntu Linux, uv, Python 3.12.15, and local FFmpeg/FFprobe 8.0.1 on PATH.
FFmpeg must include libx264 and AAC encoding, plus the scale filter's `reset_sar`
option. FFmpeg is a system dependency, not a Python package.

```bash
cd ~/Documents/Hackaton-Meta/intentcut
export UV_CACHE_DIR="$PWD/.uv-cache"
mkdir -p .tmp
export TMPDIR="$PWD/.tmp"
uv sync
```

The engine uses only the Python standard library. pytest and Ruff are development
dependencies; `uv.lock` records the resolved environment. Python 3.12.15 should
already be installed through uv. For a new machine, install it with
`uv python install 3.12.15` before setup.

## CLI and API

The destination directory must exist; the output filename must end in `.mp4`.
Existing output files (including symlinks) are refused.

```bash
uv run intentcut-render first.mp4 second.mov third.mp4 -o output.mp4
```

```python
from pathlib import Path
from intentcut import VerticalVideoRenderer

renderer = VerticalVideoRenderer()
result = renderer.render([Path("first.mp4"), Path("second.mp4")], Path("output.mp4"))
print(result.output_path, result.metadata.duration)
```

The existing function API remains supported and delegates to the same renderer:

```python
from intentcut import render_vertical_mp4

result = render_vertical_mp4(
    [Path("first.mp4"), Path("second.mp4")], Path("output.mp4")
)
```

The returned immutable `RenderResult` includes output metadata, input count and
intended timeline duration. Media failures raise `MediaError` subclasses from
`intentcut.media.models`; destination filesystem failures raise `OSError`
subclasses. CLI failures print a diagnostic to stderr and exit with status 1.

## Developer guide

Production logic lives in classes with explicit responsibilities. Start with
[`VerticalVideoRenderer.render`](src/intentcut/media/render.py) to read the entire
pipeline. The [architecture guide in Indonesian](docs/architecture.md) explains
the flow, class responsibilities, compatibility API, and how to extend the engine.

The CLI, output settings, errors, and publication rules remain unchanged. Module
functions are thin compatibility adapters; new code can use the classes directly.

For backend work, start with the [backend layout](BACKEND_ARCHITECTURE.md).
Project routes live in `backend/projects/`, upload routes and orchestration in
`backend/media_ingestion/`, and settings in `backend/shared/`. Existing import
paths remain supported. Public schemas live with their features; first-cut inputs
and shared processing contracts are independent of HTTP adapters. Database, worker,
and artifact internals retain their current structure while the frontend MVP is developed.

## Validation

Run from the project root after the setup above:

```bash
uv run pytest -v
uv run ruff check .
uv run ruff format --check .
```

Tests generate short synthetic media locally; no binary fixtures are tracked.
Integration tests require FFmpeg/FFprobe and fail if those dependencies are missing.
Test artifacts and tool caches remain under the repository and are ignored by Git.

## Rendering behavior

The first non-cover-art video and first audio stream are selected. Each clip is
scaled to fit 720x1280, preserving display aspect ratio with black padding, then
encoded with H.264/yuv420p at constant 30 FPS and AAC stereo at 48000 Hz.
Timestamps start at zero. Missing audio becomes silence; short audio is padded,
and long audio is trimmed to the video timeline. Relative audio start offsets
are retained. Video duration is preferred over container duration; container
duration is a fallback when video duration/ticks are absent. Unknown, zero,
negative, or nonfinite usable durations are rejected.

Clips are rounded up to whole 30 FPS frames. A temporary concat manifest contains
only generated filenames and explicit timeline durations. Video is copied through
the concat demuxer with preserved timestamps. Each normalized clip's AAC audio is decoded independently to respect its encoder delay,
trimmed to an exact stereo PCM sample count, and appended to a temporary audio
timeline. That timeline is encoded to AAC during final muxing. This avoids the
short silent gaps caused by concatenating AAC encoder padding directly.

FFprobe JSON verifies the output contract and a full FFmpeg decode checks playback
before publication. Staging is beside the output;
a hard link publishes the complete file atomically without overwriting another
file, even if it appears during rendering. Temporary intermediates are removed
on success or exceptions.

FFprobe has a 30-second timeout. Each FFmpeg operation allows at least five
minutes, or 20 times media duration plus one minute for longer media. No shell
commands or untrusted paths are inserted into filter expressions or manifests.

## Known limitations

- Local, finite files only; no streaming inputs, transitions, subtitles, overlays,
  audio mixing, HDR tone mapping, or editing controls.
- Duration preservation allows one video-frame rounding per clip and AAC packet
  rounding. Source timing metadata must accurately describe playable media.
- Software encoding, intermediate MP4 storage, and a full final decode cost CPU
  and disk space. The temporary PCM audio timeline uses about 192 KB per second.
  Audio undergoes two lossy AAC encodes.
- The output filesystem must support hard links (tested on Ubuntu).
- Input order/settings are deterministic; encoded bytes can vary by FFmpeg build.
- Exceptions and process timeouts clean staging files; a machine crash or forced
  process kill may leave a hidden `.intentcut-*` staging directory.

## Persistent AI outputs (M2B.7)

AI workers now publish validated MP4 and storyboard copies and atomically commit
both artifact references with lease-fenced job success. See the
[M2B.7 implementation and operations guide](M2B7_ARTIFACTS.md) for schema
initialization, worker wiring, uncertain-commit handling, and M2B.8 API guidance.

## AI job REST API (M2B.8)

Job status, artifact listing, verified MP4 downloads, and sanitized storyboard
downloads remain project-scoped and local-only. No per-user authentication or
authorization is implemented; the application must remain on trusted loopback.

## Uploaded footage to MP4 (M2B.9)

The [M2B.9 execution and acceptance guide](M2B9_UPLOADED_MEDIA.md) documents the
working upload → queued job → Muse → grounded timeline → FFmpeg → artifact flow,
budgets, API examples, worker commands, and an explicit opt-in live smoke test.
POST now returns **202** when `AI_JOBS_LOCAL_ENABLED=true`,
`AI_PROCESSING_ENABLED=true`, `MODEL_API_KEY`, and local FFmpeg/FFprobe are configured.
It returns 503 when processing is unavailable. The worker uses the submitted media
UUIDs exclusively; it has no cached `clip_b` fallback.

```sh
uv run intentcut-ai-worker --max-jobs 1
```

Workers must use the same database and storage settings as the API. API requests
never run Muse or render video. Automated acceptance tests use fake Muse responses
with real uploaded files, PostgreSQL, FFmpeg rendering, and HTTP downloads; live
provider acceptance is a separate, paid opt-in step.
