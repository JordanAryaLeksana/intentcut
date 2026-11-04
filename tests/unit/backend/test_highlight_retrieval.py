"""Six-hour deterministic retrieval fixture; never contacts a provider."""
from types import SimpleNamespace

import pytest

from intentcut.ai.highlight_retrieval import SampleRanking, request_sample_ranking, validate_ranking
from intentcut.backend.contracts import AIProcessingError
from intentcut.backend.highlights.retrieval import (
    RankedSample, coarse_times, fine_times, retrieve, select_candidates,
)


def test_six_hour_tail_event_is_retrieved_with_bounded_prompt_conditioned_scan(tmp_path, monkeypatch):
    sampled, calls, stages = [], [], []
    def frame(source, target, seconds, stream):
        sampled.append(seconds)
        target.write_bytes(b"fixture frame")
    monkeypatch.setattr("intentcut.backend.highlights.retrieval.sample_frame", frame)
    class Provider:
        def rank_highlights(self, batch, intent):
            calls.append((intent, len(batch)))
            return SampleRanking(samples=[{"sample_id": i,
                "relevance": 0.95 if (t >= 21565 if "trophy" in intent else t <= 30) else 0.0,
                "evidence": "Visible target event"} for i, t, _ in batch])
    def run(prompt, directory):
        return retrieve(tmp_path / "six-hour.mp4", directory, 21600, "source", prompt,
            8, 4, Provider(), lambda _: None, lambda: None, stages.append)
    result, _, report = run("Winner lifts trophy near the end", tmp_path / "tail")
    assert any(c.start_seconds > 21560 for c in result)
    assert all(c.end_seconds <= 21600 for c in result)
    assert min(sampled) == 0 and max(sampled) == 21599.9
    assert len(sampled) <= 72 and len(calls) <= 6
    assert all(prompt == "Winner lifts trophy near the end" and count <= 12 for prompt, count in calls)
    assert report["max_coarse_gap_seconds"] > 450  # Honest sparse sampling, not exhaustive.
    assert stages == ["discovering_highlights", "refining_highlights"]
    opening, _, _ = run("Opening title", tmp_path / "opening")
    assert all(c.start_seconds < 40 for c in opening)
    assert [(c.start_seconds, c.end_seconds) for c in result] != [(c.start_seconds, c.end_seconds) for c in opening]


def test_refinement_covers_ranked_regions_and_candidates_preserve_identity_mapping():
    coarse = [RankedSample(i, t, 0.9 if t > 21000 else 0) for i, t in enumerate(coarse_times(21600))]
    refined = fine_times(21600, coarse)
    assert len(refined) <= 24 and max(refined) > 21000
    candidates = select_candidates(coarse, 21600, "source-id", 8, 3)
    assert all(c.media_id == "source-id" and c.start_seconds <= c.probe_seconds <= c.end_seconds for c in candidates)
    assert candidates[-1].end_seconds == 21600
    assert candidates == select_candidates(list(reversed(coarse)), 21600, "source-id", 8, 3)
    assert select_candidates([RankedSample(0, 5, 0.1)], 20, "source", 8, 2) == []
    short = select_candidates([RankedSample(0, 0.1, 0.9)], 0.25, "source", 8, 2)
    assert (short[0].start_seconds, short[0].end_seconds) == (0, 0.25)


@pytest.mark.parametrize("value", [float("nan"), float("inf"), 0, -1])
def test_invalid_duration_rejected_before_sampling(value):
    with pytest.raises(ValueError): coarse_times(value)


def test_rank_contract_rejects_unknown_duplicate_missing_ids_and_timestamps():
    good = {"samples": [{"sample_id": 3, "relevance": 0.8, "evidence": "Visible trophy"}]}
    assert validate_ranking(good, [3])[0].sample_id == 3
    for value in [{"samples": []}, {"samples": good["samples"] * 2},
                  {"samples": [{**good["samples"][0], "sample_id": 4}]},
                  {"samples": [{**good["samples"][0], "start_seconds": 500}]},
                  {"samples": [{**good["samples"][0], "relevance": float("nan")}] }]:
        with pytest.raises(ValueError): validate_ranking(value, [3])


def test_no_match_is_deterministic_and_does_not_invent_candidates(tmp_path, monkeypatch):
    monkeypatch.setattr("intentcut.backend.highlights.retrieval.sample_frame", lambda _, path, *args: path.write_bytes(b"frame"))
    provider = SimpleNamespace(rank_highlights=lambda batch, intent: {"samples": [
        {"sample_id": i, "relevance": 0, "evidence": "No visible support"} for i, _, _ in batch]})
    with pytest.raises(AIProcessingError, match="no_relevant_highlights"):
        retrieve(tmp_path / "source", tmp_path / "frames", 30, "source", "trophy", 8, 4,
                 provider, lambda _: None, lambda: None, lambda _: None)


def test_provider_contract_includes_prompt_indices_and_frames_without_timestamp_authority(tmp_path):
    frame = tmp_path / "frame.jpg"; frame.write_bytes(b"fake jpeg")
    recorded = []
    def create(**kwargs):
        recorded.append(kwargs)
        return SimpleNamespace(status="completed", output_text='{"samples":[{"sample_id":7,"relevance":0.9,"evidence":"A trophy"}]}')
    provider = SimpleNamespace(responses=SimpleNamespace(create=create))
    request_sample_ranking(provider, [(7, 21599.9, frame)], "Show the trophy")
    content = recorded[0]["input"][0]["content"]
    assert "Show the trophy" in content[0]["text"]
    assert "cannot assign or change source timestamps" in content[0]["text"]
    assert "sample_id=7" in content[1]["text"] and "21599.9" in content[1]["text"]
    assert content[2]["type"] == "input_image"
    assert recorded[0]["store"] is False
