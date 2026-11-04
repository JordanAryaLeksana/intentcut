"""L6.3 acceptance: long-form highlights over real PostgreSQL + FFmpeg.

Real path only: project -> upload -> MediaAsset -> candidate discovery ->
preview -> highlight_v1 job -> worker -> EditPlan -> render -> download.
Only the Muse provider boundary is faked (tests/conftest.py fake_muse).
The synthetic source has three identifiable scenes (red, green, blue) so
rendered scene order can be verified from actual output frames.
"""

import hashlib
import subprocess
from pathlib import Path
from uuid import UUID

import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr

from intentcut.backend.ai_artifacts import AIArtifactPublisher
from intentcut.backend.app import create_app
from intentcut.backend.highlights.adapter import HighlightProcessingAdapter
from intentcut.backend.ai_worker import AIJobWorker
from intentcut.media.probe_parser import MediaProbe
from intentcut.media.render import OutputValidator

pytestmark = [pytest.mark.integration, pytest.mark.postgres]

SCENE_SECONDS = 6.0
SCENES = [("red", 0.0), ("green", 6.0), ("blue", 12.0)]
DURATION = 18.0


def scene_color_at(seconds: float) -> str:
    for name, start in reversed(SCENES):
        if seconds >= start:
            return name
    return "red"


def mean_rgb(path: Path, at_seconds: float) -> tuple[int, int, int]:
    result = subprocess.run(
        [
            "ffmpeg", "-v", "error", "-ss", str(at_seconds), "-i", str(path),
            "-vf", "crop=20:20:350:630,scale=8:8", "-frames:v", "1",
            "-f", "rawvideo", "-pix_fmt", "rgb24", "-",
        ],
        check=True, capture_output=True, timeout=30,
    )
    data = result.stdout
    pixels = len(data) // 3
    return (
        sum(data[0::3]) // pixels,
        sum(data[1::3]) // pixels,
        sum(data[2::3]) // pixels,
    )


def dominant(path: Path, at_seconds: float) -> str:
    red, green, blue = mean_rgb(path, at_seconds)
    channels = {"red": red, "green": green, "blue": blue}
    name = max(channels, key=channels.get)
    others = [v for k, v in channels.items() if k != name]
    assert channels[name] - max(others) > 35, (path, at_seconds, channels)
    return name


def full_decode(path: Path) -> None:
    subprocess.run(
        ["ffmpeg", "-v", "error", "-i", str(path), "-f", "null", "-"],
        check=True, capture_output=True, timeout=120,
    )


@pytest.fixture(scope="session")
def footage_bytes(tmp_path_factory) -> bytes:
    path = tmp_path_factory.mktemp("highlight-e2e") / "three-scenes.mp4"
    inputs: list[str] = []
    filters = []
    for index, (color, _) in enumerate(SCENES):
        inputs += [
            "-f", "lavfi", "-i",
            f"color=c={color}:s=320x180:r=30:d={SCENE_SECONDS}",
        ]
        filters.append(f"[{index}:v]noise=alls=18:allf=t,format=yuv420p[v{index}]")
    filters.append(
        "".join(f"[v{i}]" for i in range(len(SCENES)))
        + f"concat=n={len(SCENES)}:v=1:a=0[vout]"
    )
    subprocess.run(
        [
            "ffmpeg", "-hide_banner", "-loglevel", "error", "-nostdin", "-n",
            *inputs,
            "-f", "lavfi", "-i", "sine=frequency=440:sample_rate=48000",
            "-filter_complex", ";".join(filters),
            "-map", "[vout]", "-map", "3:a",
            "-t", str(DURATION), "-c:v", "libx264", "-preset", "ultrafast",
            "-crf", "26", "-c:a", "aac", "-shortest", str(path),
        ],
        check=True, capture_output=True, timeout=120,
    )
    data = path.read_bytes()
    assert 0 < len(data) < 16 * 1024 * 1024
    return data


@pytest.fixture
def hl_settings(settings):
    return settings.model_copy(
        update={
            "ai_jobs_local_enabled": True,
            "ai_processing_enabled": True,
            "model_api_key": SecretStr("fake-provider-test-only"),
            "max_file_bytes": 16 * 1024 * 1024,
            "max_request_bytes": 32 * 1024 * 1024,
        }
    )


@pytest.fixture
def storage(hl_settings):
    from intentcut.backend.storage.local_media_storage import LocalMediaStorage

    instance = LocalMediaStorage(
        hl_settings.media_root,
        hl_settings.max_file_bytes,
        hl_settings.copy_chunk_bytes,
    )
    instance.initialize()
    return instance


@pytest.fixture
def api(hl_settings, database, storage):
    app = create_app(hl_settings, database=database, storage=storage)
    with TestClient(
        app, base_url="http://127.0.0.1:8000", client=("127.0.0.1", 12345)
    ) as client:
        yield client


@pytest.fixture
def uploaded(api, footage_bytes):
    project = api.post("/projects", json={"name": "Long-form E2E"}).json()["id"]
    response = api.post(
        f"/projects/{project}/media",
        files=[("files", ("three-scenes.mp4", footage_bytes, "video/mp4"))],
    )
    assert response.status_code == 201, response.text
    media_id = response.json()["items"][0]["id"]
    return project, media_id


def get_candidates(api, project, media_id):
    response = api.get(
        f"/projects/{project}/ai-jobs/highlights/candidates",
        params={"media_id": media_id, "candidate_seconds": 4, "max_candidates": 6},
    )
    assert response.status_code == 200, response.text
    return response.json()


def submit_highlight(api, project, media_id, **changes):
    body = {
        "kind": "highlight",
        "intent": "Select the most engaging moments across the full source timeline.",
        "target_seconds": 30,
        "media_ids": [media_id],
        "candidate_seconds": 4,
        "max_candidates": 6,
        **changes,
    }
    return api.post(f"/projects/{project}/ai-jobs/highlights", json=body)


def run_worker(database, storage, hl_settings, muse, job_id) -> bool:
    worker = AIJobWorker(
        database,
        HighlightProcessingAdapter(
            database=database, storage=storage, settings=hl_settings, muse=muse
        ),
        artifact_publisher=AIArtifactPublisher(storage),
    )
    return worker.process_one(job_id=UUID(job_id))


def record_intents(fake_muse) -> list[str]:
    intents: list[str] = []
    original = fake_muse.select

    def recording(evidence, intent, target_seconds):
        intents.append(intent)
        return original(evidence, intent, target_seconds)

    fake_muse.select = recording
    return intents


def test_auto_flow_upload_discovery_render_download(
    api, uploaded, database, storage, hl_settings, fake_muse, footage_bytes, tmp_path
):
    project, media_id = uploaded

    # Upload persisted as a real MediaAsset; source bytes untouched.
    asset = database.get_media(UUID(project), UUID(media_id))
    assert asset.duration_seconds == pytest.approx(DURATION, abs=0.35)
    source_hash = hashlib.sha256(footage_bytes).hexdigest()

    # Discovery: stable IDs, bounded, spanning distinct source regions.
    listing = get_candidates(api, project, media_id)
    assert listing["media_id"] == media_id
    assert listing["sha256"] == source_hash
    candidates = listing["candidates"]
    assert len(candidates) >= 3
    starts = [c["start_seconds"] for c in candidates]
    assert starts == sorted(starts)
    assert max(starts) - min(starts) > 8.0
    for candidate in candidates:
        assert 0 <= candidate["start_seconds"] < candidate["end_seconds"]
        assert candidate["end_seconds"] <= DURATION + 1e-6
        assert candidate["media_id"] == media_id
        assert candidate["heuristic_only"] is True
    again = get_candidates(api, project, media_id)
    assert [c["id"] for c in again["candidates"]] == [c["id"] for c in candidates]
    assert [c["start_seconds"] for c in again["candidates"]] == starts

    # Preview: duration and scene color prove the original offsets.
    first = candidates[0]
    preview = api.get(
        f"/projects/{project}/ai-jobs/highlights/preview",
        params={
            "media_id": media_id,
            "start_seconds": first["start_seconds"],
            "end_seconds": first["end_seconds"],
        },
    )
    assert preview.status_code == 200, preview.text
    clip = tmp_path / "preview.mp4"
    clip.write_bytes(preview.content)
    probed = MediaProbe().probe(clip)
    expected_len = first["end_seconds"] - first["start_seconds"]
    assert probed.duration == pytest.approx(expected_len, abs=0.35)
    midpoint = (first["start_seconds"] + first["end_seconds"]) / 2
    assert dominant(clip, probed.duration / 2) == scene_color_at(midpoint)

    # AUTO job: queued over HTTP only; the worker does inference + render.
    intents = record_intents(fake_muse)
    accepted = submit_highlight(api, project, media_id)
    assert accepted.status_code == 202, accepted.text
    job_id = accepted.json()["id"]
    assert not fake_muse.analyzed
    assert run_worker(database, storage, hl_settings, fake_muse, job_id)
    assert intents == [
        "Select the most engaging moments across the full source timeline."
    ]
    status = api.get(f"/projects/{project}/ai-jobs/{job_id}").json()
    assert status["status"] == "succeeded", status

    # Storyboard: original timestamps and source identity survive intact.
    items = api.get(f"/projects/{project}/ai-jobs/{job_id}/artifacts").json()["items"]
    assert {item["kind"] for item in items} == {"storyboard", "video"}
    downloads = {item["kind"]: api.get(item["download_url"]) for item in items}
    assert all(r.status_code == 200 for r in downloads.values())
    storyboard = downloads["storyboard"].json()
    report = storyboard["highlight_discovery"]
    assert report["coarse_samples"] <= 48 and report["fine_samples"] <= 24
    offsets = {(c["start_seconds"], c["end_seconds"]) for c in report["candidates"]}
    assert len(storyboard["cuts"]) >= 2
    assert {c["media_id"] for c in storyboard["cuts"]} == {media_id}
    assert [c["playback_order"] for c in storyboard["cuts"]] == list(
        range(len(storyboard["cuts"]))
    )
    for cut in storyboard["cuts"]:
        assert (cut["start_seconds"], cut["end_seconds"]) in offsets

    # Rendered MP4: probe, full decode, and per-cut scene-order frames.
    video = tmp_path / "highlights.mp4"
    video.write_bytes(downloads["video"].content)
    metadata = MediaProbe().probe(video)
    OutputValidator().validate(metadata, storyboard["render_seconds"])
    full_decode(video)
    # Public cuts carry no per-cut render duration; segments are rendered
    # back-to-back at their source lengths (frame-quantized), so cumulative
    # source lengths locate each cut's midpoint in the output.
    cursor = 0.0
    for cut in storyboard["cuts"]:
        length = cut["end_seconds"] - cut["start_seconds"]
        assert dominant(video, cursor + length / 2) == scene_color_at(
            (cut["start_seconds"] + cut["end_seconds"]) / 2
        )
        cursor += length

    # The immutable source is byte-identical after the whole workflow.
    assert (
        hashlib.sha256(
            (storage.root / asset.storage_key).read_bytes()
        ).hexdigest()
        == source_hash
    )


def test_guided_intent_propagates_and_exclusions_hold(
    api, uploaded, database, storage, hl_settings, fake_muse
):
    project, media_id = uploaded
    candidates = get_candidates(api, project, media_id)["candidates"]
    assert len(candidates) >= 3
    excluded = candidates[0]
    included = [c["id"] for c in candidates[1:]]

    intents = record_intents(fake_muse)
    accepted = submit_highlight(
        api,
        project,
        media_id,
        intent="the tensest on-stage moments for a recap",
        candidate_ids=included,
    )
    assert accepted.status_code == 202, accepted.text
    job_id = accepted.json()["id"]
    job = database.get_ai_job(UUID(project), UUID(job_id))
    assert job.request_payload["intent"] == "the tensest on-stage moments for a recap"
    assert job.request_payload["candidate_ids"] == included

    assert run_worker(database, storage, hl_settings, fake_muse, job_id)
    assert intents == ["the tensest on-stage moments for a recap"]

    items = api.get(f"/projects/{project}/ai-jobs/{job_id}/artifacts").json()["items"]
    storyboard = api.get(
        {i["kind"]: i["download_url"] for i in items}["storyboard"]
    ).json()
    allowed = {
        (c["start_seconds"], c["end_seconds"])
        for c in candidates
        if c["id"] in included
    }
    assert storyboard["cuts"]
    for cut in storyboard["cuts"]:
        assert (cut["start_seconds"], cut["end_seconds"]) in allowed
    assert (excluded["start_seconds"], excluded["end_seconds"]) not in {
        (c["start_seconds"], c["end_seconds"]) for c in storyboard["cuts"]
    }


def test_highlight_output_enters_editing_draft_flow(
    api, uploaded, database, storage, hl_settings, fake_muse
):
    """L6.4: a completed highlight job is a valid draft/render base."""
    from intentcut.backend.editing.processor import ManualRenderProcessor

    project, media_id = uploaded
    accepted = submit_highlight(api, project, media_id)
    assert accepted.status_code == 202, accepted.text
    job_id = accepted.json()["id"]

    path = f"/projects/{project}/edit-draft"
    api_params = {"workflow": "highlights"}
    # A queued (not yet succeeded) job can never masquerade as a base:
    # its storyboard artifact does not exist, so the save is rejected.
    premature = api.put(
        path, params=api_params,
        json={
            "expected_revision": 0,
            "base_job_id": job_id,
            "base_artifact_id": job_id,
            "window_indices": [0],
        },
    )
    assert premature.status_code == 404, premature.text

    assert run_worker(database, storage, hl_settings, fake_muse, job_id)
    items = api.get(f"/projects/{project}/ai-jobs/{job_id}/artifacts").json()["items"]
    storyboard_ref = next(i for i in items if i["kind"] == "storyboard")
    published = api.get(storyboard_ref["download_url"]).json()
    body = {
        "expected_revision": 0,
        "base_job_id": job_id,
        "base_artifact_id": storyboard_ref["id"],
        "window_indices": [c["window_index"] for c in published["cuts"]],
    }
    saved = api.put(path, params=api_params, json=body)
    assert saved.status_code == 200, saved.text
    assert saved.json()["revision"] == 1
    fetched = api.get(path, params=api_params).json()["draft"]
    assert fetched == saved.json()
    assert fetched["base_job_id"] == job_id

    # The saved highlight draft renders through the existing manual path.
    admitted = api.post(path + "/renders", params=api_params, json={"revision": 1})
    assert admitted.status_code == 202, admitted.text
    render_id = admitted.json()["id"]
    manual = AIJobWorker(
        database,
        ManualRenderProcessor(database, storage, hl_settings),
        artifact_publisher=AIArtifactPublisher(storage),
    )
    assert manual.process_one(job_id=UUID(render_id))
    status = api.get(f"/projects/{project}/ai-jobs/{render_id}").json()
    assert status["status"] == "succeeded", status
    versions = api.get(path + "/renders", params=api_params).json()
    version_items = versions["items"] if isinstance(versions, dict) else versions
    assert any(v["job_id"] == render_id for v in version_items)


def test_invalid_and_stale_candidate_selections_are_rejected(
    api, uploaded, database, storage, hl_settings, fake_muse
):
    project, media_id = uploaded

    duplicate = submit_highlight(
        api, project, media_id, candidate_ids=["hl-01", "hl-01"]
    )
    assert duplicate.status_code == 422, duplicate.text

    malformed = submit_highlight(api, project, media_id, candidate_ids=["xx-1"])
    assert malformed.status_code == 422, malformed.text

    empty = submit_highlight(api, project, media_id, candidate_ids=[])
    assert empty.status_code == 422, empty.text

    # Well-formed but undiscovered: admitted, then the job fails clearly
    # instead of silently generating from nothing.
    stale = submit_highlight(api, project, media_id, candidate_ids=["hl-99"])
    assert stale.status_code == 202, stale.text
    job_id = stale.json()["id"]
    # process_one claims and finalizes the job; failure is read from status.
    assert run_worker(database, storage, hl_settings, fake_muse, job_id)
    status = api.get(f"/projects/{project}/ai-jobs/{job_id}").json()
    assert status["status"] == "failed", status
    assert status["error_code"]


