
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest
from pydantic import ValidationError

from intentcut.backend.ai_processing_adapter import (
    CachedFirstCutRequest,
    RealAIProcessingAdapter,
)


def test_reject_blank_intent():
    with pytest.raises(ValidationError):
        CachedFirstCutRequest.model_validate(
            {
                "kind": "first_cut",
                "intent": "   ",
                "target_seconds": 10,
            }
        )


def test_reject_invalid_duration():
    for seconds in (0, -1, float("inf"), 121):
        with pytest.raises(ValidationError):
            CachedFirstCutRequest.model_validate(
                {
                    "kind": "first_cut",
                    "intent": "Create a coding video",
                    "target_seconds": seconds,
                }
            )


def test_adapter_orchestrates_existing_pipeline(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    monkeypatch.setenv("MODEL_API_KEY", "unit-test-placeholder")

    evidence = tmp_path / "cached_evidence"
    evidence.mkdir()

    (evidence / "window_000.json").write_text(
        '{"window_index": 0}',
        encoding="utf-8",
    )

    job = SimpleNamespace(
        id=uuid4(),
        attempt_count=1,
        request_payload={
            "kind": "first_cut",
            "intent": "Show the coding workspace",
            "target_seconds": 10,
        },
    )

    adapter = RealAIProcessingAdapter(
        repository_root=tmp_path,
        evidence_directory=evidence,
    )

    commands = []

    def fake_run(command, *, timeout, log_path):
        commands.append(command)

        if "story_director.py" in command[1]:
            evidence_dir = Path(
                command[command.index("--evidence") + 1]
            )
            (evidence_dir / "storyboard_draft.json").write_text(
                '{"cuts": []}',
                encoding="utf-8",
            )

        if "render_storyboard.py" in command[1]:
            output = Path(
                command[command.index("--output") + 1]
            )
            output.write_bytes(b"fake-mp4-for-unit-test")

    monkeypatch.setattr(adapter, "_run", fake_run)

    result = adapter(job)

    assert result.storyboard_path.is_file()
    assert result.staged_video_path.is_file()
    assert len(commands) == 3
    assert "story_director.py" in commands[0][1]
    assert "render_storyboard.py" in commands[1][1]
    assert commands[2][0] == "ffmpeg"
