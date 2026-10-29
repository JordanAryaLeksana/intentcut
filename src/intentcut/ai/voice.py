"""Meta file ASR protocol. One HTTPS request, no retry or redirect following."""

import http.client
import json
import wave
from collections.abc import Callable
from contextlib import closing
from pathlib import Path
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field, SecretStr

from intentcut.backend.artifacts.derived import (
    CAPTION_LIMIT,
    CaptionCue,
    CaptionDocument,
)
from intentcut.backend.contracts import AIProcessingError

MODEL = "muse-voice-transcribe-1.0"
MAX_AUDIO_SECONDS = 600
MAX_REQUEST_BYTES = 32_000_000  # Conservative decimal MB, including multipart framing.
MAX_WAV_BYTES = 28_801_024  # 600 seconds of mono s16/24k PCM, plus WAV header.


class VoiceTurn(BaseModel):
    model_config = ConfigDict(extra="ignore", strict=True)
    turnId: int = Field(ge=-(2**31), le=2**31 - 1)
    startMs: int = Field(ge=0, le=600_000)
    endMs: int = Field(gt=0, le=600_000)
    transcript: str = Field(max_length=2000)
    speaker: str | None = Field(default=None, min_length=1, max_length=80)


class VoiceResponse(BaseModel):
    model_config = ConfigDict(extra="ignore", strict=True)
    sessionId: str = Field(min_length=1, max_length=256)
    transcript: str = Field(max_length=200_000)
    audioDurationMs: int = Field(gt=0, le=600_000)
    turns: list[VoiceTurn] = Field(max_length=5000)


def parse_transcript(data: bytes, duration_ms: int) -> CaptionDocument:
    """Project only documented final turn fields. Never derive word timings."""
    try:
        response = VoiceResponse.model_validate_json(data)
        if abs(response.audioDurationMs - duration_ms) > 50:
            raise ValueError("Processed duration mismatch")
        cues = []
        previous_id: int | None = None
        for turn in response.turns:
            if (
                (previous_id is not None and turn.turnId <= previous_id)
                or turn.endMs <= turn.startMs
                or turn.endMs > min(duration_ms, response.audioDurationMs)
            ):
                raise ValueError("Invalid turn identity or timing")
            previous_id = turn.turnId
            # Documented unfinished turns can have empty text; retain no fake cue.
            if turn.transcript.strip():
                cues.append(
                    CaptionCue(
                        start_ms=turn.startMs,
                        end_ms=turn.endMs,
                        text=turn.transcript,
                        speaker=turn.speaker,
                    )
                )

        def normalize(text: str) -> str:
            return " ".join(text.split())

        if normalize(response.transcript) != normalize(" ".join(c.text for c in cues)):
            raise ValueError("Untimed or inconsistent transcript")
        document = CaptionDocument(
            schema_version="captions-v1", duration_ms=duration_ms, cues=cues
        )
        if len(document.model_dump_json().encode()) > CAPTION_LIMIT:
            raise ValueError("Caption output too large")
        return document
    except (ValueError, TypeError, RecursionError) as exc:
        raise AIProcessingError("invalid_transcript") from exc


def inspect_wav(path: Path) -> tuple[int, bool]:
    """Validate full PCM payload and detect exact digital silence, not general VAD."""
    if not 44 <= path.stat().st_size <= MAX_WAV_BYTES:
        raise AIProcessingError("processing_limit")
    try:
        with wave.open(str(path), "rb") as audio:
            if (
                audio.getnchannels(),
                audio.getsampwidth(),
                audio.getframerate(),
                audio.getcomptype(),
            ) != (1, 2, 24_000, "NONE"):
                raise ValueError("Unsupported audio encoding")
            frames = audio.getnframes()
            if not 0 < frames <= MAX_AUDIO_SECONDS * 24_000:
                raise ValueError("Invalid audio duration")
            size, silent = 0, True
            while data := audio.readframes(24_000):
                size += len(data)
                silent = silent and not any(data)
            if size != frames * 2:
                raise ValueError("Truncated audio")
            return round(frames * 1000 / 24_000), silent
    except (OSError, EOFError, wave.Error, ValueError) as exc:
        raise AIProcessingError("source_unavailable") from exc


class MuseVoiceClient:
    def __init__(
        self,
        api_key: SecretStr,
        *,
        timeout: float = 180,
        connection_factory: Callable | None = None,
    ) -> None:
        self._key = api_key
        self._timeout = timeout
        self._connection_factory = connection_factory or http.client.HTTPSConnection

    def transcribe(
        self, path: Path, session_id: UUID, duration_ms: int
    ) -> CaptionDocument:
        actual_duration, _ = inspect_wav(path)
        if actual_duration != duration_ms:
            raise AIProcessingError("source_unavailable")
        boundary = f"intentcut-{uuid4().hex}"
        request = json.dumps(
            {"model": MODEL, "audioEncoding": "WAV", "mode": "ENDPOINTING"}
        )
        body = (
            (
                f'--{boundary}\r\nContent-Disposition: form-data; name="request"\r\n'
                f"Content-Type: application/json\r\n\r\n{request}\r\n"
                f"--{boundary}\r\nContent-Disposition: form-data; "
                'name="audio"; filename="audio.wav"\r\n'
                "Content-Type: audio/wav\r\n\r\n"
            ).encode()
            + path.read_bytes()
            + f"\r\n--{boundary}--\r\n".encode()
        )
        if len(body) > MAX_REQUEST_BYTES:
            raise AIProcessingError("processing_limit")
        try:
            with closing(
                self._connection_factory("api.meta.ai", timeout=self._timeout)
            ) as connection:
                connection.request(
                    "POST",
                    f"/v1/asr/transcribe?sessionId={session_id}",
                    body=body,
                    headers={
                        "Authorization": f"Bearer {self._key.get_secret_value()}",
                        "Accept": "application/json",
                        "Content-Type": f"multipart/form-data; boundary={boundary}",
                    },
                )
                with closing(connection.getresponse()) as response:
                    if response.status != 200:
                        code = (
                            "transcription_rate_limited"
                            if response.status == 429
                            else "provider_unavailable"
                        )
                        raise AIProcessingError(code)
                    if (
                        response.getheader("Content-Type", "")
                        .split(";")[0]
                        .strip()
                        .lower()
                        != "application/json"
                    ):
                        raise AIProcessingError("invalid_transcript")
                    data = response.read(CAPTION_LIMIT + 1)
                    if len(data) > CAPTION_LIMIT:
                        raise AIProcessingError("invalid_transcript")
        except (OSError, http.client.HTTPException) as exc:
            # The remote request may already have been processed. Never retry here.
            raise AIProcessingError("transcription_outcome_unknown") from exc
        return parse_transcript(data, duration_ms)
