"""Assert the existing M2A wire contract and remote cleanup without networking."""

import json
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from intentcut.ai.muse import MODEL, MuseClient, analyze_one
from intentcut.ai.schemas import VideoUnderstandingResult
from intentcut.ai.story_director import StorySelection, request_story


@pytest.fixture
def provider():
    client = Mock()
    client.files.create.return_value = SimpleNamespace(id="remote-private-id")
    result = VideoUnderstandingResult.model_validate(
        {
            "summary": "An establishing shot",
            "scene_candidates": [
                {
                    "description": "A blue sky",
                    "editorial_reason": "Set the scene",
                    "start_seconds": None,
                    "end_seconds": None,
                }
            ],
        }
    )
    client.responses.create.return_value = SimpleNamespace(
        status="completed", output_text=result.model_dump_json(), usage=None
    )
    return client


def test_upload_structured_understanding_and_cleanup(provider, tmp_path):
    clip = tmp_path / "window.mp4"
    clip.write_bytes(b"fake transport bytes")
    result, metrics = analyze_one(provider, clip)
    assert result.summary == "An establishing shot"
    args = provider.files.create.call_args.kwargs
    assert args["purpose"] == "user_data"
    assert args["expires_after"]["seconds"] == 3600
    assert args["file"].closed
    args = provider.responses.create.call_args.kwargs
    assert args["model"] == MODEL and args["store"] is False
    assert args["text"]["format"]["strict"] is True
    assert args["max_output_tokens"] == 1500
    assert args["input"][0]["content"][1]["file_id"] == "remote-private-id"
    provider.files.delete.assert_called_once_with("remote-private-id")
    assert metrics["total_tokens"] is None


@pytest.mark.parametrize("failure", ["transport", "incomplete", "malformed", "empty"])
def test_remote_file_cleaned_on_failure(provider, tmp_path, failure):
    clip = tmp_path / "window.mp4"
    clip.write_bytes(b"fake")
    if failure == "transport":
        provider.responses.create.side_effect = RuntimeError("network")
    elif failure == "incomplete":
        provider.responses.create.return_value.status = "incomplete"
    else:
        provider.responses.create.return_value.output_text = (
            "{" if failure == "malformed" else ""
        )
    with pytest.raises((ValueError, RuntimeError)):
        analyze_one(provider, clip)
    provider.files.delete.assert_called_once_with("remote-private-id")


def test_remote_cleanup_failure_uses_expiry_fallback(provider, tmp_path, capsys):
    clip = tmp_path / "window.mp4"
    clip.write_bytes(b"fake")
    provider.files.delete.side_effect = RuntimeError("private credentials")
    assert MuseClient(provider).analyze(clip).summary
    assert "one hour" in capsys.readouterr().err


def test_director_wire_contract(provider):
    result = StorySelection.model_validate(
        {
            "title": "Story",
            "rationale": "Contrast",
            "selected_windows": [{"window_index": 1, "reason": "Opening"}],
        }
    )
    provider.responses.create.return_value.output_text = result.model_dump_json()
    evidence = [{"window_index": 1, "summary": "Blue sky", "render_seconds": 5}]
    actual, _ = request_story(provider, evidence, "Tell a story", 10)
    assert actual == result
    args = provider.responses.create.call_args.kwargs
    assert args["model"] == MODEL and args["store"] is False
    assert json.dumps(evidence) in args["input"]
    assert "media IDs" in args["input"]
    assert args["text"]["format"]["schema"] == StorySelection.model_json_schema()
    provider.files.create.assert_not_called()
