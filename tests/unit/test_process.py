import subprocess

import pytest

from intentcut.media.models import MediaProcessError, MissingBinaryError
from intentcut.media.process import render_timeout, run_process


@pytest.mark.parametrize(
    ("failure", "expected", "message"),
    [
        (FileNotFoundError(), MissingBinaryError, "not found"),
        (PermissionError("denied"), MediaProcessError, "Cannot run"),
        (subprocess.TimeoutExpired("ffmpeg", 30), MediaProcessError, "timed out"),
        (
            subprocess.CalledProcessError(1, "ffmpeg", stderr="broken input"),
            MediaProcessError,
            "broken input",
        ),
    ],
)
def test_process_errors(monkeypatch, failure, expected, message):
    def fail(*args, **kwargs):
        raise failure

    monkeypatch.setattr(subprocess, "run", fail)
    with pytest.raises(expected, match=message):
        run_process(["ffmpeg", "-version"], timeout=30)


def test_arguments_are_passed_without_a_shell(monkeypatch):
    arguments = ["ffprobe", "strange ' ; $(file).mp4"]

    def check(command, **kwargs):
        assert command == arguments
        assert not kwargs.get("shell", False)
        assert kwargs["timeout"] == 30
        assert kwargs["stdin"] == subprocess.DEVNULL
        return subprocess.CompletedProcess(command, 0, stdout="{}", stderr="")

    monkeypatch.setattr(subprocess, "run", check)
    assert run_process(arguments, timeout=30) == "{}"


def test_render_timeout_scales_for_long_media():
    assert render_timeout(1) == 300
    assert render_timeout(3600) > 3600
