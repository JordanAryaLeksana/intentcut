from unittest.mock import create_autospec

import pytest

from intentcut.media.cli import RenderCLI
from intentcut.media.models import InvalidMediaError, MediaProcessError
from intentcut.media.render import VerticalVideoRenderer


@pytest.mark.parametrize(
    "failure",
    [
        InvalidMediaError("invalid input"),
        MediaProcessError("encoding failed"),
        FileExistsError("output already exists"),
        PermissionError("destination denied"),
    ],
)
def test_cli_reports_render_failures_on_stderr(failure, capsys):
    renderer = create_autospec(VerticalVideoRenderer, instance=True)
    renderer.render.side_effect = failure

    status = RenderCLI(renderer).run(["a.mp4", "b.mp4", "-o", "out.mp4"])

    captured = capsys.readouterr()
    assert status == 1
    assert captured.out == ""
    assert captured.err == f"intentcut-render: {failure}\n"


@pytest.mark.parametrize(
    ("arguments", "status"),
    [(["--help"], 0), ([], 2), (["a.mp4", "b.mp4"], 2)],
)
def test_cli_argument_handling_does_not_start_rendering(arguments, status):
    renderer = create_autospec(VerticalVideoRenderer, instance=True)

    with pytest.raises(SystemExit) as error:
        RenderCLI(renderer).run(arguments)

    assert error.value.code == status
    renderer.render.assert_not_called()
