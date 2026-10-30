"""Plain-text caption admission and fixed timing validation; no subprocesses."""

import pytest

from intentcut.backend.captions.schemas import (
    CueEdit,
    SaveCaptions,
    SavedCue,
    validate_saved_cues,
)


@pytest.mark.parametrize(
    "text", ["hello\x00world", "bad\x01", "bad\r", "bad\x1b[0m", "hidden\u202e"]
)
def test_control_characters_rejected(text):
    with pytest.raises(ValueError):
        CueEdit(index=0, text=text, enabled=True)


@pytest.mark.parametrize(
    "text", [r"%{n} {\an8}", "<b>literal</b>", "Unicode café\nnext line", "tab\ttext"]
)
def test_plain_text_is_not_filter_or_markup_code(text):
    assert CueEdit(index=0, text=text, enabled=True).text == text


def test_disabled_blank_text_does_not_invent_a_cue():
    cue = SavedCue(index=0, start_ms=100, end_ms=200, text="   ", enabled=False)
    validate_saved_cues([cue], 1000)
    assert cue.text == "   " and not cue.enabled
    with pytest.raises(ValueError):
        CueEdit(index=0, text="  ", enabled=True)


@pytest.mark.parametrize("revision", [0, -1, True, 1.5])
def test_revision_is_strict_positive_integer(revision):
    with pytest.raises(ValueError):
        SaveCaptions(expected_revision=revision, cues=[])


def test_text_limit_and_timestamps_are_not_editable():
    with pytest.raises(ValueError):
        CueEdit(index=0, text="x" * 2001, enabled=True)
    with pytest.raises(ValueError):
        CueEdit(index=0, text="text", enabled=True, start_ms=0)
    with pytest.raises(ValueError):
        validate_saved_cues(
            [SavedCue(index=0, start_ms=200, end_ms=100, text="x", enabled=False)], 1000
        )


def test_overlapping_captions_cannot_silently_render_outside_small_frame(
    tmp_path, monkeypatch
):
    from fractions import Fraction
    from types import SimpleNamespace
    from unittest.mock import Mock

    import intentcut.backend.captions.render as renderer
    from intentcut.backend.contracts import AIProcessingError

    metadata = SimpleNamespace(
        duration=2,
        audio=None,
        video=SimpleNamespace(start_time=0, width=160, height=90),
    )
    monkeypatch.setattr(
        renderer, "MediaProbe", lambda: SimpleNamespace(probe=lambda _: metadata)
    )
    monkeypatch.setattr(renderer, "frame_info", lambda _: (48, Fraction(24)))
    runner = Mock()
    monkeypatch.setattr(renderer, "ProcessRunner", lambda: runner)
    cues = [
        SavedCue(index=i, start_ms=300, end_ms=1500, text="Overlap", enabled=True)
        for i in range(2)
    ]
    with pytest.raises(AIProcessingError, match="processing_limit"):
        renderer.burn_captions(tmp_path / "source", tmp_path / "out.mp4", cues, 2000)
    runner.run_ffmpeg.assert_not_called()
