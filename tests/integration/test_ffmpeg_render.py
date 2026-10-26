import array
import json
import math
import shutil
import subprocess
import sys
from fractions import Fraction

import pytest

from intentcut import VerticalVideoRenderer, render_vertical_mp4
from intentcut.media.models import InvalidMediaError, MediaProcessError
from intentcut.media.probe_parser import probe_media

pytestmark = pytest.mark.integration


def ffmpeg(*arguments):
    return subprocess.run(
        [
            "ffmpeg",
            "-hide_banner",
            "-loglevel",
            "error",
            "-nostdin",
            "-xerror",
            *arguments,
        ],
        check=True,
        capture_output=True,
        timeout=90,
    ).stdout


@pytest.fixture(scope="module")
def clips(tmp_path_factory):
    assert shutil.which("ffmpeg"), "Integration tests require FFmpeg on PATH"
    assert shutil.which("ffprobe"), "Integration tests require FFprobe on PATH"
    directory = tmp_path_factory.mktemp("synthetic")

    def make(name, color, size, rate, duration, tones=(), sar="1"):
        path = directory / name
        args = [
            "-n",
            "-f",
            "lavfi",
            "-i",
            f"color=c={color}:s={size}:r={rate}:d={duration}",
        ]
        for frequency, audio_duration in tones:
            args += [
                "-f",
                "lavfi",
                "-i",
                f"sine=frequency={frequency}:sample_rate=44100:duration={audio_duration}",
            ]
        args += ["-map", "0:v:0"]
        for index in range(len(tones)):
            args += ["-map", f"{index + 1}:a:0"]
        args += [
            "-vf",
            f"setsar={sar}",
            "-c:v",
            "libx264",
            "-preset",
            "ultrafast",
            "-threads",
            "2",
            "-bf",
            "0",
            "-pix_fmt",
            "yuv420p",
            "-c:a",
            "aac",
            "-b:a",
            "128k",
            str(path),
        ]
        ffmpeg(*args)
        return path

    return {
        "red": make(
            "red ' ; $(literal) [x]\nclip.mp4",
            "red",
            "320x180",
            "24",
            0.8,
            [(440, 0.84)],
        ),
        "blue": make("blue.mp4", "blue", "180x320", "60", 0.7),
        "green": make(
            "green.mp4", "lime", "160x160", "15", 0.6, [(880, 0.2), (1600, 0.6)]
        ),
        "yellow": make(
            "yellow.mp4", "yellow", "144x256", "30000/1001", 0.8, [(660, 0.85)], sar="2"
        ),
    }


@pytest.fixture(
    scope="module",
    params=[render_vertical_mp4, VerticalVideoRenderer().render],
    ids=["function_api", "class_api"],
)
def rendered(clips, tmp_path_factory, request):
    output = tmp_path_factory.mktemp("result") / "ordered.mp4"
    result = request.param([clips[c] for c in ["red", "blue", "green"]], output)
    return result, [probe_media(clips[c]).duration for c in ["red", "blue", "green"]]


def decoded_rgb(path, timestamp, crop="crop=2:2:359:639"):
    return ffmpeg(
        "-i",
        str(path),
        "-ss",
        str(timestamp),
        "-frames:v",
        "1",
        "-vf",
        crop,
        "-pix_fmt",
        "rgb24",
        "-f",
        "rawvideo",
        "-",
    )[:3]


def decoded_audio(path):
    data = ffmpeg(
        "-i",
        str(path),
        "-vn",
        "-ac",
        "1",
        "-ar",
        "48000",
        "-c:a",
        "pcm_s16le",
        "-f",
        "s16le",
        "-",
    )
    samples = array.array("h", data)
    if sys.byteorder != "little":
        samples.byteswap()
    return samples


def rms(samples, start, end):
    window = samples[round(start * 48000) : round(end * 48000)]
    assert window
    return math.sqrt(sum(value * value for value in window) / len(window))


def dominant_frequency(samples, start, end):
    window = samples[round(start * 48000) : round(end * 48000)]
    crossings = sum(a <= 0 < b for a, b in zip(window, window[1:], strict=False))
    return crossings / (len(window) / 48000)


def test_output_contract_and_duration(rendered):
    result, durations = rendered
    metadata = probe_media(result.output_path)
    video, audio = metadata.video, metadata.audio
    assert (video.codec, video.width, video.height, video.pixel_format) == (
        "h264",
        720,
        1280,
        "yuv420p",
    )
    assert video.frame_rate == video.nominal_frame_rate == Fraction(30)
    assert (audio.codec, audio.sample_rate, audio.channels) == ("aac", 48000, 2)
    assert metadata.duration == pytest.approx(
        sum(durations), abs=len(durations) / 30 + 0.05
    )
    assert result.input_count == 3
    assert result.metadata.path == result.output_path
    assert not list(result.output_path.parent.glob(".intentcut-*"))


def test_color_order_and_full_frame_padding(rendered):
    result, _ = rendered
    for timestamp, dominant in [(0.4, 0), (1.1, 2), (1.8, 1)]:
        pixel = decoded_rgb(result.output_path, timestamp)
        assert len(pixel) == 3
        assert pixel[dominant] > 180
        assert all(pixel[index] < 40 for index in range(3) if index != dominant)
    assert max(decoded_rgb(result.output_path, 0.4, "crop=2:2:359:19")) < 10
    assert decoded_rgb(result.output_path, 1.1, "crop=2:2:359:19")[2] > 180
    # 16:9 red fits the full width and has its expected ~405-pixel display height.
    assert decoded_rgb(result.output_path, 0.4, "crop=2:2:3:639")[0] > 180
    assert max(decoded_rgb(result.output_path, 0.4, "crop=2:2:359:399")) < 10


def test_audio_preserved_silence_inserted_and_first_stream_selected(rendered):
    result, _ = rendered
    samples = decoded_audio(result.output_path)
    assert rms(samples, 0.1, 0.6) > 500
    assert dominant_frequency(samples, 0.1, 0.6) == pytest.approx(440, abs=8)
    assert rms(samples, 1.0, 1.4) < 10  # Clip with no source audio.
    assert dominant_frequency(samples, 1.56, 1.69) == pytest.approx(880, abs=20)
    assert rms(samples, 1.9, 2.08) < 10  # Short first audio padded; second ignored.


def test_complete_file_decodes_and_faststart_is_present(rendered):
    result, _ = rendered
    ffmpeg(
        "-i",
        str(result.output_path),
        "-map",
        "0:v:0",
        "-map",
        "0:a:0",
        "-f",
        "null",
        "-",
    )
    data = result.output_path.read_bytes()
    assert data.index(b"moov") < data.index(b"mdat")


def test_constant_frame_timestamps_and_monotonic_packets(rendered):
    result, _ = rendered
    raw = subprocess.run(
        [
            "ffprobe",
            "-v",
            "error",
            "-show_packets",
            "-of",
            "json",
            str(result.output_path),
        ],
        check=True,
        capture_output=True,
        text=True,
        timeout=30,
    )
    packets = json.loads(raw.stdout)["packets"]
    for kind in ("video", "audio"):
        selected = [packet for packet in packets if packet["codec_type"] == kind]
        dts = [float(packet["dts_time"]) for packet in selected]
        assert all(b > a for a, b in zip(dts, dts[1:], strict=False))
        if kind == "video":
            pts = sorted(float(packet["pts_time"]) for packet in selected)
            assert pts[0] == pytest.approx(0, abs=0.001)
            assert all(
                b - a == pytest.approx(1 / 30, abs=0.00001)
                for a, b in zip(pts, pts[1:], strict=False)
            )


def test_adjacent_audio_has_no_silent_boundary_gaps(clips, tmp_path):
    paths = [clips["red"], clips["yellow"], clips["red"], clips["yellow"]]
    result = render_vertical_mp4(paths, tmp_path / "adjacent.mp4")
    samples = decoded_audio(result.output_path)
    duration = 0
    for path in paths[:-1]:
        duration += math.ceil(probe_media(path).duration * 30 - 1e-7) / 30
        # Every 10ms window near a join must retain tone energy.
        for offset in (-0.02, -0.01, 0, 0.01, 0.02):
            assert rms(samples, duration + offset, duration + offset + 0.01) > 250
    assert len(samples) / 48000 == pytest.approx(result.intended_duration, abs=0.05)
    # Non-square source pixels must retain display aspect ratio: yellow needs padding.
    yellow_pixel = decoded_rgb(result.output_path, 1.1)
    assert yellow_pixel[0] > 180 and yellow_pixel[1] > 180
    assert max(decoded_rgb(result.output_path, 1.1, "crop=2:2:359:19")) < 10


def test_missing_corrupt_and_audio_only_inputs(clips, tmp_path):
    corrupt = tmp_path / "corrupt.mp4"
    corrupt.write_bytes(b"this is not a video")
    audio = tmp_path / "audio.m4a"
    ffmpeg("-f", "lavfi", "-i", "sine=duration=0.2", "-c:a", "aac", str(audio))
    for invalid in [tmp_path / "missing.mp4", corrupt, audio]:
        output = tmp_path / "failed.mp4"
        with pytest.raises((InvalidMediaError, MediaProcessError)):
            render_vertical_mp4([clips["red"], invalid], output)
        assert not output.exists()
        assert not list(tmp_path.glob(".intentcut-*"))


def test_cli_success_and_failure(clips, tmp_path):
    output = tmp_path / "cli.mp4"
    command = [
        "intentcut-render",
        str(clips["blue"]),
        str(clips["red"]),
        "-o",
        str(output),
    ]
    result = subprocess.run(command, capture_output=True, text=True, timeout=120)
    assert result.returncode == 0, result.stderr
    assert "Rendered 2 clips" in result.stdout
    assert decoded_rgb(output, 0.3)[2] > 180
    assert decoded_rgb(output, 1.0)[0] > 180
    before = output.read_bytes()
    failed = subprocess.run(command, capture_output=True, text=True, timeout=30)
    assert failed.returncode == 1
    assert "already exists" in failed.stderr
    assert output.read_bytes() == before


def test_renderer_reuse_after_failure_keeps_timelines_independent(clips, tmp_path):
    renderer = VerticalVideoRenderer()
    with pytest.raises(InvalidMediaError):
        renderer.render([clips["red"], tmp_path / "missing.mp4"], tmp_path / "bad.mp4")

    first = renderer.render([clips["red"], clips["blue"]], tmp_path / "first.mp4")
    second = renderer.render([clips["blue"], clips["green"]], tmp_path / "second.mp4")

    assert first.output_path != second.output_path
    assert first.intended_duration != second.intended_duration
    assert decoded_rgb(first.output_path, 0.3)[0] > 180
    assert decoded_rgb(second.output_path, 0.3)[2] > 180
    assert decoded_rgb(second.output_path, 1.0)[1] > 180
    assert not (tmp_path / "bad.mp4").exists()
    assert not list(tmp_path.glob(".intentcut-*"))
