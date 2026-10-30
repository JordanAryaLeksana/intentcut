"""Official multipart contract and final-turn parsing, without provider calls."""

import io
import json
import struct
import wave
from email import policy
from email.parser import BytesParser
from uuid import uuid4

import pytest
from pydantic import SecretStr

from intentcut.ai.voice import MuseVoiceClient, inspect_wav, parse_transcript
from intentcut.backend.artifacts.derived import CaptionArtifactResult
from intentcut.backend.contracts import AIProcessingError
from intentcut.backend.jobs.dispatch import JobDispatcher, JobRegistration, JobType
from intentcut.backend.storage.database_models import AIJob


def response(**changes):
    return {
        "sessionId": "fixture",
        "transcript": "Hello there.",
        "audioDurationMs": 1000,
        "turns": [
            {"turnId": 1, "startMs": 250, "endMs": 800, "transcript": "Hello there."}
        ],
        **changes,
    }


def encode(value):
    return json.dumps(value).encode()


def test_timed_turns_and_allowlist():
    data = response(provider_diagnostics="do-not-publish")
    data["turns"][0]["internal_path"] = "/private"
    doc = parse_transcript(encode(data), 1000)
    cue = doc.cues[0]
    assert (cue.start_ms, cue.end_ms, cue.text, cue.speaker) == (
        250,
        800,
        "Hello there.",
        None,
    )
    assert (
        "private" not in doc.model_dump_json()
        and "diagnostics" not in doc.model_dump_json()
    )


@pytest.mark.parametrize(
    "turns", [[], [{"turnId": 1, "startMs": 100, "endMs": 200, "transcript": ""}]]
)
def test_no_speech_and_unfinished_empty_turn(turns):
    assert (
        parse_transcript(encode(response(transcript="", turns=turns)), 1000).cues == []
    )


@pytest.mark.parametrize(
    "change",
    [
        {"audioDurationMs": 900},
        {"audioDurationMs": True},
        {"audioDurationMs": 1000.0},
        {"transcript": "Untimed", "turns": []},
        {"transcript": 1},
        {"turns": None},
        {"sessionId": ""},
    ],
)
def test_invalid_envelope(change):
    with pytest.raises(AIProcessingError) as error:
        parse_transcript(encode(response(**change)), 1000)
    assert error.value.code == "invalid_transcript"


@pytest.mark.parametrize(
    "change",
    [
        {"startMs": -1},
        {"endMs": 1001},
        {"endMs": 100},
        {"startMs": True},
        {"startMs": 250.5},
        {"turnId": 2**31},
        {"transcript": "x" * 2001},
        {"speaker": ""},
    ],
)
def test_invalid_turns(change):
    data = response()
    data["turns"][0].update(change)
    with pytest.raises(AIProcessingError):
        parse_transcript(encode(data), 1000)


@pytest.mark.parametrize("kind", ["id", "time", "text"])
def test_inconsistent_or_unordered_turns(kind):
    data = response(transcript="Hello there. Again.")
    turn = {"turnId": 2, "startMs": 800, "endMs": 900, "transcript": "Again."}
    if kind == "id":
        turn["turnId"] = 1
    elif kind == "time":
        turn["startMs"] = 0
    else:
        turn["transcript"] = "Different."
    data["turns"].append(turn)
    with pytest.raises(AIProcessingError):
        parse_transcript(encode(data), 1000)


@pytest.mark.parametrize("data", [b"{", b"[]", b"null", b"{}"])
def test_malformed_response(data):
    with pytest.raises(AIProcessingError):
        parse_transcript(data, 1000)


def write_wav(path, *, rate=24000, channels=1, width=2, frames=24000, silent=False):
    with wave.open(str(path), "wb") as wav:
        wav.setnchannels(channels)
        wav.setsampwidth(width)
        wav.setframerate(rate)
        wav.writeframes(
            (b"\0\0" if silent else struct.pack("<h", 1000)) * frames * channels
        )
    return path


class HTTPResponse(io.BytesIO):
    status = 200

    def getheader(self, name, default=None):
        return "application/json" if name == "Content-Type" else default


class Connection:
    def __init__(self, response):
        self.response, self.calls, self.closed = response, [], False

    def request(self, *args, **kwargs):
        self.calls.append((args, kwargs))

    def getresponse(self):
        return self.response

    def close(self):
        self.closed = True


def test_exact_multipart_and_connection_lifecycle(tmp_path):
    path = write_wav(tmp_path / "audio.wav")
    reply = HTTPResponse(encode(response()))
    connection = Connection(reply)
    endpoints = []

    def factory(host, **kwargs):
        endpoints.append((host, kwargs))
        return connection

    client = MuseVoiceClient(SecretStr("fake-key"), connection_factory=factory)
    session = uuid4()
    document = client.transcribe(path, session, 1000)
    assert document.cues[0].start_ms == 250
    assert endpoints == [("api.meta.ai", {"timeout": 180})]
    assert len(connection.calls) == 1
    args, kwargs = connection.calls[0]
    assert args == ("POST", f"/v1/asr/transcribe?sessionId={session}")
    headers = kwargs["headers"]
    assert headers["Authorization"] == "Bearer fake-key"
    assert headers["Accept"] == "application/json"
    message = BytesParser(policy=policy.default).parsebytes(
        f"Content-Type: {headers['Content-Type']}\r\n\r\n".encode() + kwargs["body"]
    )
    parts = list(message.iter_parts())
    assert [p.get_param("name", header="content-disposition") for p in parts] == [
        "request",
        "audio",
    ]
    assert parts[0].get_content_type() == "application/json"
    assert json.loads(parts[0].get_payload(decode=True)) == {
        "model": "muse-voice-transcribe-1.0",
        "mode": "ENDPOINTING",
        "audioEncoding": "WAV",
    }
    assert parts[1].get_content_type() == "audio/wav"
    assert parts[1].get_payload(decode=True) == path.read_bytes()
    assert connection.closed and reply.closed


@pytest.mark.parametrize("status", [301, 400, 401, 429, 500])
def test_provider_http_errors_never_retry(tmp_path, status):
    path = write_wav(tmp_path / "audio.wav")
    reply = HTTPResponse(b"raw private diagnostic")
    reply.status = status
    connection = Connection(reply)
    client = MuseVoiceClient(
        SecretStr("fake-key"), connection_factory=lambda *a, **k: connection
    )
    with pytest.raises(AIProcessingError) as error:
        client.transcribe(path, uuid4(), 1000)
    expected = "transcription_rate_limited" if status == 429 else "provider_unavailable"
    assert error.value.code == expected
    assert len(connection.calls) == 1 and connection.closed and reply.closed
    assert "private" not in str(error.value) and "fake-key" not in str(error.value)


def test_timeout_closes_connection_without_retry(tmp_path):
    path = write_wav(tmp_path / "audio.wav")
    connection = Connection(None)

    def timeout():
        raise TimeoutError("private-details")

    connection.getresponse = timeout
    client = MuseVoiceClient(
        SecretStr("fake-key"), connection_factory=lambda *a, **k: connection
    )
    with pytest.raises(AIProcessingError, match="transcription_outcome_unknown"):
        client.transcribe(path, uuid4(), 1000)
    assert len(connection.calls) == 1 and connection.closed


@pytest.mark.parametrize(
    "params", [{"rate": 16000}, {"channels": 2}, {"width": 1}, {"frames": 0}]
)
def test_invalid_wav_encoding_or_duration(tmp_path, params):
    path = write_wav(tmp_path / "bad.wav", **params)
    with pytest.raises(AIProcessingError):
        inspect_wav(path)


def test_wav_silence_and_truncation(tmp_path):
    path = write_wav(tmp_path / "audio.wav", silent=True)
    assert inspect_wav(path) == (1000, True)
    data = path.read_bytes()
    path.write_bytes(data[:-100])
    with pytest.raises(AIProcessingError):
        inspect_wav(path)


def test_voice_job_cannot_route_to_first_cut(tmp_path):
    from unittest.mock import Mock

    from intentcut.backend.contracts import ProcessingResult

    first_cut = Mock()
    dispatcher = JobDispatcher(
        [JobRegistration(JobType.UPLOADED_FIRST_CUT, first_cut, ProcessingResult)]
    )
    with pytest.raises(AIProcessingError, match="unsupported_job_type"):
        dispatcher(AIJob(request_payload={"pipeline_version": "caption_transcribe_v1"}))
    first_cut.assert_not_called()
    result = CaptionArtifactResult(tmp_path / "captions.json", None)
    dispatcher = JobDispatcher(
        [
            JobRegistration(
                JobType.CAPTION_TRANSCRIBE, lambda job: result, CaptionArtifactResult
            )
        ]
    )
    assert (
        dispatcher(AIJob(request_payload={"pipeline_version": "caption_transcribe_v1"}))
        is result
    )


@pytest.mark.parametrize("damage", ["content_type", "size", "json"])
def test_invalid_provider_response_closes_resources(tmp_path, damage):
    path = write_wav(tmp_path / "audio.wav")
    reply = HTTPResponse(b"{" if damage == "json" else b" " * (1024 * 1024 + 1))
    if damage == "content_type":
        reply.getheader = lambda *a: "text/html"
    connection = Connection(reply)
    client = MuseVoiceClient(
        SecretStr("fake"), connection_factory=lambda *a, **kw: connection
    )
    with pytest.raises(AIProcessingError, match="invalid_transcript"):
        client.transcribe(path, uuid4(), 1000)
    assert len(connection.calls) == 1 and connection.closed and reply.closed


def test_wav_file_limit_prevents_any_http_connection(tmp_path):
    from unittest.mock import Mock

    from intentcut.ai.voice import MAX_WAV_BYTES

    path = tmp_path / "oversized.wav"
    with path.open("wb") as stream:
        stream.truncate(MAX_WAV_BYTES + 1)
    connection = Mock()
    client = MuseVoiceClient(SecretStr("fake"), connection_factory=connection)
    with pytest.raises(AIProcessingError, match="processing_limit"):
        client.transcribe(path, uuid4(), 600000)
    connection.assert_not_called()


def test_provider_ten_minute_duration_cap(tmp_path):
    path = tmp_path / "too-long.wav"
    frames = 600 * 24000 + 1
    path.write_bytes(
        struct.pack(
            "<4sI4s4sIHHIIHH4sI",
            b"RIFF",
            36 + frames * 2,
            b"WAVE",
            b"fmt ",
            16,
            1,
            1,
            24000,
            48000,
            2,
            16,
            b"data",
            frames * 2,
        )
    )
    with pytest.raises(AIProcessingError):
        inspect_wav(path)
