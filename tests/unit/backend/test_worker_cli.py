from unittest.mock import Mock

import pytest
from pydantic import SecretStr

from intentcut.backend import worker_cli
from intentcut.backend.ai_media_inputs import processing_available


@pytest.mark.parametrize(
    "change",
    [
        {"ai_processing_enabled": False},
        {"model_api_key": None},
        {"model_api_key": SecretStr(" ")},
    ],
)
def test_worker_refuses_unconfigured_provider(settings, monkeypatch, change):
    settings = settings.model_copy(
        update={
            "ai_processing_enabled": True,
            "model_api_key": SecretStr("test-secret"),
            **change,
        }
    )
    connect = Mock()
    monkeypatch.setattr(worker_cli.Database, "connect", connect)
    with pytest.raises(ValueError, match="not configured"):
        worker_cli.run_worker(settings)
    connect.assert_not_called()


def test_missing_ffmpeg_fails_closed(settings, monkeypatch):
    settings = settings.model_copy(
        update={
            "ai_processing_enabled": True,
            "model_api_key": SecretStr("test-secret"),
        }
    )
    monkeypatch.setattr(
        "intentcut.backend.ai_media_inputs.shutil.which", lambda _: None
    )
    assert not processing_available(settings)


def test_cli_does_not_print_provider_credentials(settings, monkeypatch, capsys):
    monkeypatch.setattr(worker_cli, "BackendSettings", lambda: settings)
    monkeypatch.setattr(
        worker_cli,
        "run_worker",
        Mock(side_effect=RuntimeError("private-provider-secret")),
    )
    assert worker_cli.main([]) == 1
    output = capsys.readouterr()
    assert "private-provider-secret" not in output.err
    assert "RuntimeError" in output.err


def test_cli_shutdown(settings, monkeypatch, capsys):
    monkeypatch.setattr(worker_cli, "BackendSettings", lambda: settings)
    monkeypatch.setattr(worker_cli, "run_worker", Mock(side_effect=KeyboardInterrupt))
    assert worker_cli.main([]) == 130
    assert "interrupted" in capsys.readouterr().out


@pytest.mark.parametrize("args", [["--max-jobs", "0"], ["--max-attempts", "4"]])
def test_cli_budgets(args):
    with pytest.raises(SystemExit) as exc:
        worker_cli.main(args)
    assert exc.value.code == 2


def test_smoke_script_without_live_is_inert():
    import subprocess
    import sys
    from pathlib import Path

    script = Path(__file__).resolve().parents[3] / "scripts" / "smoke_uploaded_job.py"
    result = subprocess.run(
        [sys.executable, str(script), "/nonexistent/footage.mp4"],
        check=True,
        capture_output=True,
        text=True,
        timeout=20,
    )
    assert "No requests made" in result.stdout
    assert result.stderr == ""
