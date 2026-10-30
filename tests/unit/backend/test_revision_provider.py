"""Structured text-only provider transport and strict public proposal validation."""

import json
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from intentcut.ai.revision import RevisionSelection, request_revision, validate_revision


def proposed(indices):
    return {
        "outcome": "proposed",
        "window_indices": indices,
        "explanation": "Reorder the existing sequence.",
        "reasons": [
            {"window_index": i, "reason": "Creator requested this order."}
            for i in indices
        ],
    }


def test_text_only_muse_request_has_strict_schema_and_no_file_upload():
    client = Mock()
    client.responses.create.return_value = SimpleNamespace(
        status="completed", output_text=json.dumps(proposed([2, 1]))
    )
    result = request_revision(
        client,
        {
            "current_sequence": [1, 2],
            "cuts": [{"window_index": 1}, {"window_index": 2}],
        },
        "Reverse the cuts",
    )
    assert result.window_indices == [2, 1]
    kwargs = client.responses.create.call_args.kwargs
    assert kwargs["model"] == "muse-spark-1.3" and kwargs["store"] is False
    assert kwargs["text"]["format"]["strict"] is True
    assert kwargs["input"][0]["role"] == "system"
    assert "input_file" not in json.dumps(kwargs)
    client.files.create.assert_not_called()


@pytest.mark.parametrize("indices", [[999], [2, 2], [], [1, 2], [-1]])
def test_rejects_invalid_or_noop_sequence(indices):
    with pytest.raises(ValueError):
        validate_revision(RevisionSelection.model_validate(proposed(indices)), [1, 2])


def test_removal_and_unsupported_are_explicit():
    assert validate_revision(
        RevisionSelection.model_validate(proposed([1])), [1, 2]
    ).window_indices == [1]
    unsupported = {
        "outcome": "unsupported",
        "window_indices": [],
        "explanation": "Adding music is not supported.",
        "reasons": [],
    }
    assert (
        validate_revision(RevisionSelection.model_validate(unsupported), [1, 2]).outcome
        == "unsupported"
    )
    with pytest.raises(ValueError):
        validate_revision(
            RevisionSelection.model_validate({**unsupported, "window_indices": [1]}),
            [1, 2],
        )


@pytest.mark.parametrize(
    "change", [{"operations": [{"trim": 2}]}, {"media_id": "other-project"}]
)
def test_unsupported_fields_are_rejected(change):
    with pytest.raises(ValueError):
        RevisionSelection.model_validate({**proposed([2, 1]), **change})


@pytest.mark.parametrize(
    "text",
    [
        "/home/private/evidence",
        "https://internal.example/",
        "api_key=private",
        "Bearer token",
    ],
)
def test_private_model_prose_is_not_a_public_explanation(text):
    with pytest.raises(ValueError):
        RevisionSelection.model_validate({**proposed([2, 1]), "explanation": text})


def test_invalid_or_incomplete_provider_result_is_rejected():
    client = Mock()
    client.responses.create.return_value = SimpleNamespace(
        status="incomplete", output_text="private raw text"
    )
    with pytest.raises(ValueError):
        request_revision(client, {"current_sequence": [1, 2]}, "Reverse")
