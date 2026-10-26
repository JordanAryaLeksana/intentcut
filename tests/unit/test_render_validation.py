from dataclasses import replace
from fractions import Fraction
from pathlib import Path

import pytest

from intentcut.media import render
from intentcut.media.models import (
    AudioStream,
    InvalidMediaError,
    MediaMetadata,
    MediaProcessError,
    OutputValidationError,
    VideoStream,
)


@pytest.fixture
def valid_media():
    return MediaMetadata(
        Path("test.mp4"),
        1.0,
        VideoStream(0, "h264", 720, 1280, "yuv420p", Fraction(30), Fraction(30), 0),
        AudioStream(1, "aac", 48000, 2, 0),
    )


def test_valid_output(valid_media):
    render.validate_output(valid_media, 1.0)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("codec", "hevc"),
        ("width", 1080),
        ("height", 1920),
        ("pixel_format", "yuv444p"),
        ("frame_rate", Fraction(25)),
        ("nominal_frame_rate", Fraction(60)),
        ("start_time", 0.5),
    ],
)
def test_reject_wrong_video(valid_media, field, value):
    media = replace(valid_media, video=replace(valid_media.video, **{field: value}))
    with pytest.raises(OutputValidationError):
        render.validate_output(media, 1.0)


@pytest.mark.parametrize(
    ("field", "value"),
    [("codec", "mp3"), ("sample_rate", 44100), ("channels", 1), ("start_time", 0.5)],
)
def test_reject_wrong_audio(valid_media, field, value):
    media = replace(valid_media, audio=replace(valid_media.audio, **{field: value}))
    with pytest.raises(OutputValidationError):
        render.validate_output(media, 1.0)


@pytest.mark.parametrize("duration", [0, -1, float("nan"), float("inf"), 2])
def test_reject_bad_output_duration(valid_media, duration):
    with pytest.raises(OutputValidationError):
        render.validate_output(replace(valid_media, duration=duration), 1.0)


def test_reject_missing_output_audio(valid_media):
    with pytest.raises(OutputValidationError):
        render.validate_output(replace(valid_media, audio=None), 1.0)


@pytest.mark.parametrize("paths", [[], [Path("one.mp4")]])
def test_reject_fewer_than_two_inputs(tmp_path, paths):
    with pytest.raises(InvalidMediaError, match="At least two"):
        render.render_vertical_mp4(paths, tmp_path / "output.mp4")
    assert not list(tmp_path.iterdir())


def test_existing_output_is_untouched(tmp_path):
    target = tmp_path / "output.mp4"
    target.write_bytes(b"keep me")
    with pytest.raises(FileExistsError):
        render.render_vertical_mp4([Path("a"), Path("b")], target)
    assert target.read_bytes() == b"keep me"


def test_dangling_output_symlink_is_refused(tmp_path):
    target = tmp_path / "output.mp4"
    target.symlink_to(tmp_path / "absent")
    with pytest.raises(FileExistsError):
        render.render_vertical_mp4([Path("a"), Path("b")], target)
    assert target.is_symlink()


def test_wrong_output_extension(tmp_path):
    with pytest.raises(InvalidMediaError, match=".mp4"):
        render.render_vertical_mp4([Path("a"), Path("b")], tmp_path / "out.mkv")


def test_missing_output_parent(tmp_path):
    with pytest.raises(FileNotFoundError, match="directory"):
        render.render_vertical_mp4(
            [Path("a"), Path("b")], tmp_path / "missing" / "out.mp4"
        )


@pytest.mark.parametrize(
    "stage",
    ["normalize", "audio", "concat", "probe_output", "validate", "decode", "publish"],
)
def test_failure_cleans_intermediates_and_never_publishes(
    tmp_path, monkeypatch, valid_media, stage
):
    def probe(self, path):
        if stage == "probe_output" and path.name == "render.mp4":
            raise MediaProcessError("output probe failed")
        return replace(
            valid_media, path=path, duration=2 if path.name == "render.mp4" else 1
        )

    def normalize(self, source, target, duration):
        target.write_bytes(b"partial segment")
        if stage == "normalize":
            raise MediaProcessError("normalization failed")

    def ffmpeg(self, arguments, **kwargs):
        if kwargs.get("cwd"):
            (kwargs["cwd"] / "render.mp4").write_bytes(b"staged")
            if stage == "concat":
                raise MediaProcessError("concat failed")
        elif stage == "decode":
            raise MediaProcessError("decode failed")

    def validate(*args):
        if stage == "validate":
            raise OutputValidationError("validation failed")

    def append_audio(self, segment, duration, combined):
        combined.write_bytes(b"partial audio")
        if stage == "audio":
            raise OutputValidationError("audio sample count failed")

    def publish(*args):
        raise PermissionError("publication failed")

    monkeypatch.setattr(render.MediaProbe, "probe", probe)
    monkeypatch.setattr(render.ClipNormalize, "normalize", normalize)
    monkeypatch.setattr(render.AudioTimeline, "append", append_audio)
    monkeypatch.setattr(render.ProcessRunner, "run_ffmpeg", ffmpeg)
    monkeypatch.setattr(render.OutputValidator, "validate", validate)
    if stage == "publish":
        monkeypatch.setattr(render.os, "link", publish)
    with pytest.raises((MediaProcessError, OutputValidationError, PermissionError)):
        render.render_vertical_mp4([Path("a"), Path("b")], tmp_path / "output.mp4")
    assert not list(tmp_path.iterdir())


def test_destination_created_during_render_is_never_replaced(
    tmp_path, monkeypatch, valid_media
):
    output = tmp_path / "output.mp4"
    monkeypatch.setattr(
        render.MediaProbe,
        "probe",
        lambda self, path: replace(
            valid_media, duration=2 if path.name == "render.mp4" else 1
        ),
    )
    monkeypatch.setattr(render.ClipNormalize, "normalize", lambda *args: None)
    monkeypatch.setattr(render.AudioTimeline, "append", lambda *args: None)

    def ffmpeg(self, arguments, **kwargs):
        if kwargs.get("cwd"):
            (kwargs["cwd"] / "render.mp4").write_bytes(b"staged")
        else:
            output.write_bytes(b"created by another process")

    monkeypatch.setattr(render.ProcessRunner, "run_ffmpeg", ffmpeg)
    with pytest.raises(FileExistsError):
        render.render_vertical_mp4([Path("a"), Path("b")], output)
    assert output.read_bytes() == b"created by another process"
    assert list(tmp_path.iterdir()) == [output]
