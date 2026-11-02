"""Focused highlights coverage: discovery, mapping, contracts, admission.

Pure discovery tests use an injected sampler (no FFmpeg, no media files);
six-hour timestamp arithmetic is verified without generating huge fixtures.
"""

from datetime import UTC, datetime
from uuid import uuid4

import pytest
from pydantic import ValidationError

from intentcut.ai.story_director import (
    GroundedWindow,
    StorySelection,
    build_edit_plan,
)
from intentcut.ai.temporal_windows import TemporalWindow
from intentcut.backend.ai_job_service import AIJobAPIError, AIJobService
from intentcut.backend.highlights.contracts import (
    HighlightRequest,
    UploadedHighlightRequest,
)
from intentcut.backend.highlights.discovery import (
    Candidate,
    FrameSignals,
    center_window,
    discover_candidates,
    plan_probes,
    score_signals,
)
from intentcut.backend.highlights.service import HighlightService
from intentcut.backend.shared.settings import BackendSettings
from intentcut.backend.storage.database_models import MediaAsset


def flat_sampler(value: float = 0.5):
    def sample(t: float) -> FrameSignals:
        del t
        return FrameSignals(y_avg=128.0, sat_avg=128.0 * value * 2, blur=1.0)

    return sample


def peaked_sampler(peaks: dict[float, float]):
    """Score peaks near given timestamps; deterministic for coverage tests."""

    def sample(t: float) -> FrameSignals:
        closeness = min((abs(t - p) for p in peaks), default=1e9)
        hot = any(abs(t - p) < 1.0 for p in peaks)
        _ = closeness
        sat = 200.0 if hot else 20.0
        return FrameSignals(y_avg=128.0, sat_avg=sat, blur=1.0)

    return sample


def test_plan_probes_span_full_timeline_even_at_six_hours():
    duration = 6 * 3600.0
    probes = plan_probes(duration, strata=12, probes_per_stratum=5)
    assert len(probes) == 60
    assert probes[0] > 0
    assert probes[-1] < duration
    width = duration / 12
    for s in range(12):
        cells = probes[s * 5 : (s + 1) * 5]
        assert all(s * width < t < (s + 1) * width for t in cells)


def test_discovery_covers_every_stratum_with_flat_signals():
    found = discover_candidates(3600.0, "media-1", flat_sampler(), max_candidates=8)
    assert len(found) == 8
    # Winners spread across the hour; first starts near 0, last ends near 3600.
    assert found[0].start_seconds < 450.0
    assert found[-1].end_seconds > 3150.0
    assert [c.id for c in found] == [f"hl-{i + 1:02d}" for i in range(8)]


def test_discovery_prefers_strong_signals_without_claiming_meaning():
    found = discover_candidates(
        600.0,
        "media-1",
        peaked_sampler({500.0: 1.0}),
        candidate_seconds=10.0,
        max_candidates=4,
    )
    best = max(found, key=lambda c: c.score)
    assert 490.0 <= best.probe_seconds <= 510.0
    assert set(best.components) == {"exposure", "color", "sharpness"}


def test_discovery_deduplicates_overlapping_winners():
    # Short source: per-stratum winners would overlap, NMS keeps spaced ones.
    found = discover_candidates(
        30.0,
        "media-1",
        flat_sampler(),
        candidate_seconds=8.0,
        max_candidates=8,
        probes_per_stratum=3,
        min_gap_seconds=1.0,
    )
    assert 1 <= len(found) <= 8
    ordered = sorted(found, key=lambda c: c.start_seconds)
    for left, right in zip(ordered, ordered[1:], strict=False):
        assert right.start_seconds >= left.end_seconds + 1.0 - 1e-9


def test_discovery_rejects_invalid_budgets():
    with pytest.raises(ValueError):
        discover_candidates(60.0, "m", flat_sampler(), max_candidates=13)
    with pytest.raises(ValueError):
        discover_candidates(60.0, "m", flat_sampler(), max_candidates=0)
    with pytest.raises(ValueError):
        discover_candidates(60.0, "", flat_sampler())


def test_discovery_rejects_nonpositive_duration():
    with pytest.raises(ValueError):
        discover_candidates(0.0, "m", flat_sampler())


def test_center_window_clamps_fractional_boundaries():
    start, end = center_window(0.5, 21600.0, 8.0)
    assert (start, end) == (0.0, 8.0)
    start, end = center_window(21599.5, 21600.0, 8.0)
    assert (start, end) == (21592.0, 21600.0)
    assert center_window(100.123456789, 1000.0, 8.0)[0] == round(96.123456789, 6)


def test_center_window_short_source_yields_full_span():
    assert center_window(2.0, 5.0, 8.0) == (0.0, 5.0)


def test_candidate_offsets_map_identity_to_temporal_windows():
    """Original offsets need no rebase: windows carry source coordinates."""
    found = discover_candidates(
        8130.5,  # 02:15:30 region arithmetic without a 6h file
        "media-1",
        flat_sampler(),
        candidate_seconds=8.0,
        max_candidates=12,
    )
    windows = [
        TemporalWindow(
            index=i, start_seconds=c.start_seconds, end_seconds=c.end_seconds
        )
        for i, c in enumerate(found)
    ]
    for candidate, window in zip(found, windows, strict=True):
        assert window.start_seconds == candidate.start_seconds
        assert window.end_seconds == candidate.end_seconds
        assert 0 <= window.start_seconds < window.end_seconds <= 8130.5


def test_six_hour_identity_mapping_at_mission_example():
    candidate = Candidate(
        id="hl-01",
        media_id="media-1",
        start_seconds=2 * 3600 + 15 * 60 + 30,
        end_seconds=2 * 3600 + 15 * 60 + 38,
        score=0.9,
        components={},
        probe_seconds=8134.0,
    )
    window = TemporalWindow(
        index=0,
        start_seconds=candidate.start_seconds,
        end_seconds=candidate.end_seconds,
    )
    assert (window.start_seconds, window.end_seconds) == (8130.0, 8138.0)
    assert window.duration_seconds == 8.0


def test_score_signals_is_deterministic_and_bounded():
    signals = FrameSignals(y_avg=128.0, sat_avg=200.0, blur=2.0)
    first = score_signals(signals)
    assert score_signals(signals) == first
    assert 0.0 <= first[0] <= 1.0


def test_highlight_request_contracts():
    media = uuid4()
    body = HighlightRequest.model_validate(
        {
            "kind": "highlight",
            "intent": "a tense thriller recap",
            "target_seconds": 30.0,
            "media_ids": [str(media)],
        }
    )
    assert body.max_candidates == 8
    with pytest.raises(ValidationError):
        HighlightRequest.model_validate(
            {
                "kind": "highlight",
                "intent": "x",
                "target_seconds": 30.0,
                "media_ids": [str(media), str(uuid4())],
            }
        )
    with pytest.raises(ValidationError):
        HighlightRequest.model_validate(
            {
                "kind": "first_cut",
                "intent": "x",
                "target_seconds": 30.0,
                "media_ids": [str(media)],
            }
        )
    digest = "ab" * 32
    persisted = UploadedHighlightRequest.model_validate(
        {
            **body.model_dump(mode="json"),
            "pipeline_version": "highlight_v1",
            "source_sha256": {str(media): digest},
        }
    )
    assert persisted.source_sha256 == {str(media): digest}
    with pytest.raises(ValidationError):
        UploadedHighlightRequest.model_validate(
            {
                **body.model_dump(mode="json"),
                "pipeline_version": "highlight_v1",
                "source_sha256": {str(uuid4()): digest},
            }
        )


def test_highlight_candidate_selection_contract():
    media = uuid4()
    base = {
        "kind": "highlight",
        "intent": "recap",
        "target_seconds": 30.0,
        "media_ids": [str(media)],
    }
    assert HighlightRequest.model_validate(base).candidate_ids is None
    selected = HighlightRequest.model_validate(
        {**base, "candidate_ids": ["hl-01", "hl-03"]}
    )
    assert selected.candidate_ids == ["hl-01", "hl-03"]
    for bad in ([], ["hl-01", "hl-01"], ["nope"], ["hl-1"]):
        with pytest.raises(ValidationError):
            HighlightRequest.model_validate({**base, "candidate_ids": bad})


def _highlight_settings(tmp_path, **overrides):
    values = {
        "_env_file": None,
        "database_url": "postgresql+psycopg://unused:unused@localhost/intentcut_test",
        "media_root": tmp_path / "media",
        "ai_jobs_local_enabled": True,
        "ai_processing_enabled": True,
        "model_api_key": "test-key",
    }
    values.update(overrides)
    return BackendSettings(**values)


def _asset(project_id, **overrides):
    values = {
        "id": uuid4(),
        "project_id": project_id,
        "original_filename": "long.mp4",
        "storage_key": f"key-{uuid4().hex}",
        "size_bytes": 1024,
        "duration_seconds": 3600.0,
        "width": 1920,
        "height": 1080,
        "frame_rate_numerator": 30,
        "frame_rate_denominator": 1,
        "video_codec": "h264",
        "video_stream_index": 0,
        "audio_stream_index": None,
        "audio_codec": None,
        "audio_sample_rate": None,
        "audio_channels": None,
        "created_at": datetime.now(UTC),
    }
    values.update(overrides)
    return MediaAsset(**values)


def test_highlight_admission_rejects_over_budget_media(tmp_path, database):
    from intentcut.backend.storage.local_media_storage import LocalMediaStorage

    settings = _highlight_settings(tmp_path)
    storage = LocalMediaStorage(
        settings.media_root, settings.max_file_bytes, settings.copy_chunk_bytes
    )
    storage.initialize()
    service = HighlightService(AIJobService(database, storage, settings))
    project = database.create_project("hl")
    big = _asset(project.id, size_bytes=settings.highlight_max_source_bytes + 1)
    database.save_media_assets(project.id, [big])
    body = HighlightRequest(
        kind="highlight",
        intent="recap",
        target_seconds=30.0,
        media_ids=[big.id],
    )
    with pytest.raises(AIJobAPIError) as exc:
        service.create(project.id, body)
    assert exc.value.code == "processing_limit"
    long = _asset(
        project.id, duration_seconds=settings.highlight_max_duration_seconds + 1
    )
    database.save_media_assets(project.id, [long])
    with pytest.raises(AIJobAPIError) as exc:
        service.create(
            project.id,
            HighlightRequest(
                kind="highlight",
                intent="recap",
                target_seconds=30.0,
                media_ids=[long.id],
            ),
        )
    assert exc.value.code == "processing_limit"


def test_highlight_admission_unavailable_without_provider(tmp_path, database):
    from intentcut.backend.storage.local_media_storage import LocalMediaStorage

    settings = _highlight_settings(tmp_path, ai_processing_enabled=False)
    storage = LocalMediaStorage(
        settings.media_root, settings.max_file_bytes, settings.copy_chunk_bytes
    )
    storage.initialize()
    service = HighlightService(AIJobService(database, storage, settings))
    project = database.create_project("hl")
    asset = _asset(project.id)
    database.save_media_assets(project.id, [asset])
    with pytest.raises(AIJobAPIError) as exc:
        service.create(
            project.id,
            HighlightRequest(
                kind="highlight",
                intent="recap",
                target_seconds=30.0,
                media_ids=[asset.id],
            ),
        )
    assert exc.value.status == 503


def test_build_edit_plan_supports_multiple_cuts_from_one_source(tmp_path):
    """Mission §0A: one media ID may yield several playback cuts (mocked Muse)."""
    media_id = uuid4()
    windows = [
        GroundedWindow(
            media_id=media_id,
            window_index=i,
            source_window_index=i,
            start_seconds=start,
            end_seconds=start + 8.0,
            render_seconds=8.0,
            clip=tmp_path / f"w{i}.mp4",
            sha256="ab" * 32,
            summary="s",
            observations=[],
        )
        for i, start in enumerate([8130.0, 120.0, 5400.0])
    ]
    selection = StorySelection.model_validate(
        {
            "title": "Highlights",
            "rationale": "mocked provider choice",
            "selected_windows": [
                {"window_index": 1, "reason": "hook"},
                {"window_index": 0, "reason": "climax at 02:15:30"},
                {"window_index": 2, "reason": "payoff"},
            ],
        }
    )
    plan = build_edit_plan(selection, windows, [media_id], 30.0)
    assert [c.media_id for c in plan.cuts] == [media_id] * 3
    assert [c.playback_order for c in plan.cuts] == [0, 1, 2]
    assert (plan.cuts[1].start_seconds, plan.cuts[1].end_seconds) == (8130.0, 8138.0)
    assert plan.total_seconds == 24.0
