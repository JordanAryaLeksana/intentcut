import json
from dataclasses import replace
from uuid import uuid4

import pytest

from intentcut.ai.temporal_windows import TemporalWindow
from intentcut.ai.video_understanding import (
    PreparedWindow,
    WindowUnderstanding,
    file_digest,
)


@pytest.fixture
def prepared(tmp_path):
    path = tmp_path / "window.mp4"
    path.write_bytes(b"fake-window")
    return PreparedWindow(
        media_id=uuid4(),
        index=0,
        window=TemporalWindow(0, 0, 5),
        source_sha256="a" * 64,
        clip=path,
        sha256=file_digest(path),
        render_seconds=5,
    )


def test_cache_reuses_validated_grounding(tmp_path, prepared, fake_muse):
    analyzer = WindowUnderstanding(fake_muse)
    calls = []
    first = analyzer.analyze(prepared, tmp_path, lambda: calls.append(1))
    second = analyzer.analyze(prepared, tmp_path, lambda: calls.append(1))
    assert first == second
    assert calls == [1]
    assert first.media_id == prepared.media_id
    assert len(fake_muse.analyzed) == 1
    assert all("source_media" not in obs for obs in first.observations)


@pytest.mark.parametrize(
    "change",
    [
        {"media_id": uuid4()},
        {"source_sha256": "b" * 64},
        {"window": TemporalWindow(1, 5, 10)},
    ],
)
def test_cache_cannot_alias_other_sources(tmp_path, prepared, fake_muse, change):
    analyzer = WindowUnderstanding(fake_muse)
    analyzer.analyze(prepared, tmp_path, lambda: None)
    other = replace(prepared, **change)
    analyzer.analyze(other, tmp_path, lambda: None)
    assert len(fake_muse.analyzed) == 2
    assert analyzer.cache_path(prepared, tmp_path) != analyzer.cache_path(
        other, tmp_path
    )


@pytest.mark.parametrize("fault", ["identity", "timestamps", "symlink", "bad_json"])
def test_tampered_cache_is_rejected(tmp_path, prepared, fake_muse, fault):
    analyzer = WindowUnderstanding(fake_muse)
    analyzer.analyze(prepared, tmp_path, lambda: None)
    path = analyzer.cache_path(prepared, tmp_path)
    data = json.loads(path.read_text())
    if fault == "identity":
        data["identity"]["media_id"] = str(uuid4())
        path.write_text(json.dumps(data))
    elif fault == "timestamps":
        data["result"]["scene_candidates"][0].update(start_seconds=1, end_seconds=2)
        path.write_text(json.dumps(data))
    elif fault == "bad_json":
        path.write_text("{")
    else:
        target = tmp_path / "moved"
        path.rename(target)
        path.symlink_to(target)
    with pytest.raises((ValueError, OSError)):
        analyzer.analyze(prepared, tmp_path, lambda: None)
    assert len(fake_muse.analyzed) == 1


def test_changed_window_is_never_sent(tmp_path, prepared, fake_muse):
    prepared.clip.write_bytes(b"changed")
    with pytest.raises(ValueError, match="fingerprint"):
        WindowUnderstanding(fake_muse).analyze(prepared, tmp_path, lambda: None)
    assert not fake_muse.analyzed
