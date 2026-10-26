import json
from copy import deepcopy
from fractions import Fraction
from pathlib import Path
from unittest.mock import create_autospec

import pytest

from intentcut.media.models import InvalidMediaError
from intentcut.media.probe_parser import MediaProbe, ProbeParser, parse_probe_json, probe_media
from intentcut.media.process_runner import PROBE_TIMEOUT, ProcessRunner


@pytest.fixture
def payload():
    return {
        "streams": [
            {
                "index": 0,
                "codec_type": "video",
                "codec_name": "h264",
                "width": 320,
                "height": 180,
                "pix_fmt": "yuv420p",
                "avg_frame_rate": "30000/1001",
                "r_frame_rate": "30000/1001",
                "duration": "1.25",
                "start_time": "0.0",
            },
            {
                "index": 1,
                "codec_type": "audio",
                "codec_name": "aac",
                "sample_rate": "44100",
                "channels": 1,
            },
        ],
        "format": {"duration": "9.0"},
    }


def test_video_duration_and_first_audio_take_precedence(payload):
    payload["streams"].append({"index": 2, "codec_type": "audio"})
    media = parse_probe_json(json.dumps(payload), Path("clip.mp4"))
    assert media.duration == 1.25
    assert media.video.frame_rate == Fraction(30000, 1001)
    assert media.audio.index == 1
    assert media.audio.sample_rate == 44100


def test_missing_audio_and_attached_cover(payload):
    cover = deepcopy(payload["streams"][0])
    cover["disposition"] = {"attached_pic": 1}
    cover["index"] = 2
    payload["streams"] = [cover, payload["streams"][0]]
    media = parse_probe_json(json.dumps(payload), Path("clip.mp4"))
    assert media.audio is None
    assert media.video.index == 0


@pytest.mark.parametrize("duration", ["0", "-1", "nan", "inf", "garbage"])
def test_reject_bad_video_duration_even_with_valid_container(payload, duration):
    payload["streams"][0]["duration"] = duration
    with pytest.raises(InvalidMediaError):
        parse_probe_json(json.dumps(payload), Path("bad.mp4"))


def test_duration_ticks_fallback(payload):
    video = payload["streams"][0]
    video.pop("duration")
    video.update(duration_ts=90, time_base="1/30")
    assert parse_probe_json(json.dumps(payload), Path("clip.mp4")).duration == 3


def test_container_duration_fallback(payload):
    payload["streams"][0]["duration"] = "N/A"
    assert parse_probe_json(json.dumps(payload), Path("clip.mp4")).duration == 9


def test_unknown_duration(payload):
    payload["streams"][0].pop("duration")
    payload.pop("format")
    with pytest.raises(InvalidMediaError):
        parse_probe_json(json.dumps(payload), Path("clip.mp4"))


@pytest.mark.parametrize("raw", ["not json", "null", "[]", "{}", '{"streams": []}'])
def test_malformed_metadata(raw):
    with pytest.raises(InvalidMediaError):
        parse_probe_json(raw, Path("bad.mp4"))


def test_audio_only_metadata(payload):
    payload["streams"].pop(0)
    with pytest.raises(InvalidMediaError, match="No usable video"):
        parse_probe_json(json.dumps(payload), Path("audio.m4a"))


def test_zero_dimensions(payload):
    payload["streams"][0]["width"] = 0
    with pytest.raises(InvalidMediaError):
        parse_probe_json(json.dumps(payload), Path("bad.mp4"))


@pytest.mark.parametrize("rate", ["0/0", "N/A", "-1", None])
def test_unknown_frame_rate_does_not_preclude_decoding(payload, rate):
    payload["streams"][0]["avg_frame_rate"] = rate
    assert parse_probe_json(json.dumps(payload), Path("clip.mp4")).video.frame_rate == 0


def test_missing_file_and_directory(tmp_path):
    for path in [tmp_path / "missing.mp4", tmp_path]:
        with pytest.raises(InvalidMediaError, match="regular file"):
            probe_media(path)


def test_probe_uses_supplied_runner_and_preserves_absolute_path(tmp_path, payload):
    path = tmp_path / "clip.mp4"
    path.touch()
    runner = create_autospec(ProcessRunner, instance=True)
    runner.run.return_value = json.dumps(payload)

    media = MediaProbe(runner=runner).probe(path)

    assert media == ProbeParser().parse(json.dumps(payload), path.absolute())
    runner.run.assert_called_once_with(
        [
            "ffprobe",
            "-v",
            "error",
            "-show_streams",
            "-show_format",
            "-of",
            "json",
            str(path),
        ],
        timeout=PROBE_TIMEOUT,
    )
