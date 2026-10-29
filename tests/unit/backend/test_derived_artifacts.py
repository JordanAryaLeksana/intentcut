"""Strict derived contracts; fixtures are local bytes, never provider outputs."""

import json
from pathlib import Path
from unittest.mock import Mock
from uuid import uuid4

import pytest

from intentcut.backend.ai_artifacts import AIArtifactPublisher
from intentcut.backend.ai_worker import AIJobWorker
from intentcut.backend.artifacts.derived import (
    CAPTION_LIMIT,
    ArtifactParent,
    CaptionArtifactResult,
    ImageArtifactResult,
    VideoRenditionResult,
    image_content_type,
    validate_caption,
)
from intentcut.backend.contracts import AIProcessingError, ProcessingResult
from intentcut.backend.jobs.dispatch import JobDispatcher, JobRegistration, JobType
from intentcut.backend.storage.database_models import AIJob


def caption(**updates):
    return json.dumps(
        {"schema_version": "captions-v1", "duration_ms": 250, "cues": [], **updates}
    ).encode()


def test_silence_and_actual_segment_timestamps():
    assert validate_caption(caption()).cues == []
    doc = validate_caption(
        caption(cues=[{"start_ms": 1, "end_ms": 200, "text": "Fixture"}])
    )
    assert doc.cues[0].end_ms == 200


@pytest.mark.parametrize(
    "data",
    [
        b"",
        b"not json",
        b"[]",
        b"{",
        b" " * (CAPTION_LIMIT + 1),
        caption(cues=[{"start_ms": 0, "end_ms": 300, "text": "Too long"}]),
        caption(cues=[{"start_ms": 10, "end_ms": 2, "text": "Reversed"}]),
        caption(cues=[{"start_ms": 0, "end_ms": 10, "text": " "}]),
        caption(cues=[{"start_ms": 0, "end_ms": 10, "text": "Ok", "path": "/private"}]),
        caption(duration_ms=True),
        caption(internal_response="secret"),
        caption(
            cues=[
                {"start_ms": 10, "end_ms": 20, "text": "a"},
                {"start_ms": 0, "end_ms": 5, "text": "b"},
            ]
        ),
    ],
)
def test_invalid_caption_rejected(data):
    with pytest.raises(ValueError):
        validate_caption(data)


@pytest.mark.parametrize("data", [b"invalid", b"GIF89a", b"RIFFxxxxWEBP", b"<svg/>"])
def test_unsupported_image_headers(data):
    with pytest.raises(ValueError):
        image_content_type(data)


@pytest.mark.parametrize(
    "identifier,checksum", [("not UUID", "a" * 64), (uuid4(), "X" * 64)]
)
def test_invalid_parent(identifier, checksum):
    with pytest.raises(ValueError):
        ArtifactParent(identifier, checksum)


@pytest.mark.parametrize(
    "kind,result_type",
    [
        (JobType.CAPTION_ARTIFACT, CaptionArtifactResult),
        (JobType.IMAGE_ARTIFACT, ImageArtifactResult),
        (JobType.VIDEO_RENDITION, VideoRenditionResult),
    ],
)
def test_typed_dispatch_and_publisher_required(kind, result_type):
    parent = ArtifactParent(uuid4(), "a" * 64)
    output = result_type(Path("fixture"), parent)
    handler = Mock(return_value=output)
    dispatcher = JobDispatcher([JobRegistration(kind, handler, result_type)])
    job = AIJob(request_payload={"pipeline_version": kind.value})
    assert dispatcher(job) is output
    assert dispatcher.requires_artifact_publisher
    with pytest.raises(ValueError, match="artifact publication"):
        AIJobWorker(Mock(), dispatcher)
    handler.return_value = ProcessingResult(Path("a"), Path("b"))
    with pytest.raises(AIProcessingError):
        dispatcher(job)


def test_unknown_artifact_kind_has_no_video_fallback(tmp_path):
    publisher = AIArtifactPublisher(Mock())
    with pytest.raises(ValueError, match="Unsupported artifact kind"):
        publisher._prepare(uuid4(), uuid4(), "unknown", tmp_path / "missing", tmp_path)


def test_unknown_result_does_not_publish():
    storage = Mock()
    publisher = AIArtifactPublisher(storage)
    with pytest.raises(ValueError, match="Unsupported result type"):
        publisher.publish_and_complete(Mock(), uuid4(), uuid4(), uuid4(), object())
    storage.publish.assert_not_called()


@pytest.mark.parametrize("width,height", [(0, 10), (8193, 1), (8192, 8192)])
def test_image_dimensions_rejected_before_decode(tmp_path, width, height):
    from intentcut.backend.artifacts.derived import validate_image

    path = tmp_path / "image"
    path.write_bytes(b"\x89PNG\r\n\x1a\nfixture")
    runner = Mock()
    runner.run.return_value = json.dumps(
        {"streams": [{"codec_name": "png", "width": width, "height": height}]}
    )
    with pytest.raises(ValueError, match="dimensions"):
        validate_image(path, runner)
    assert runner.run.call_count == 1
    runner.run_ffmpeg.assert_not_called()


def test_multiple_image_frames_rejected(tmp_path):
    from intentcut.backend.artifacts.derived import validate_image

    path = tmp_path / "image"
    path.write_bytes(b"\x89PNG\r\n\x1a\nfixture")
    runner = Mock()
    runner.run.side_effect = [
        json.dumps({"streams": [{"codec_name": "png", "width": 10, "height": 10}]}),
        json.dumps({"streams": [{"nb_read_frames": "2"}]}),
    ]
    with pytest.raises(ValueError, match="single decoded image"):
        validate_image(path, runner)
    runner.run_ffmpeg.assert_not_called()


def test_oversized_image_rejected_before_probe(tmp_path):
    from intentcut.backend.artifacts.derived import IMAGE_LIMIT, validate_image

    path = tmp_path / "too-large"
    with path.open("wb") as stream:
        stream.truncate(IMAGE_LIMIT + 1)
    runner = Mock()
    with pytest.raises(ValueError, match="image size"):
        validate_image(path, runner)
    runner.run.assert_not_called()
