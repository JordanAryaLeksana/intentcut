"""Only plain text and enabled flags are editable; source timing is immutable."""

import unicodedata
from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

PIPELINE = "caption_burn_v1"


def validate_text(text: str) -> str:
    if any(
        (unicodedata.category(c) == "Cc" and c not in "\n\t")
        or c in "\u202a\u202b\u202c\u202d\u202e\u2066\u2067\u2068\u2069"
        for c in text
    ):
        raise ValueError("Unsupported caption control character")
    return text


class CueEdit(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    index: int = Field(ge=0)
    text: str = Field(max_length=2000)
    enabled: bool

    @model_validator(mode="after")
    def valid(self):
        validate_text(self.text)
        if self.enabled and not self.text.strip():
            raise ValueError("Enabled captions need text")
        return self


class SavedCue(CueEdit):
    start_ms: int = Field(ge=0)
    end_ms: int = Field(gt=0)


class CreateCaptions(BaseModel):
    model_config = ConfigDict(extra="forbid")
    transcription_artifact_id: UUID


class SaveCaptions(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expected_revision: int = Field(ge=1, strict=True)
    cues: list[CueEdit] = Field(max_length=5000)


class ExportCaptions(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expected_revision: int = Field(ge=1, strict=True)


class CaptionSetResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: UUID
    project_id: UUID
    parent_artifact_id: UUID
    parent_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    transcription_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    revision: int = Field(ge=1, strict=True)
    duration_ms: int = Field(gt=0, le=86400000, strict=True)
    cues: list[SavedCue] = Field(max_length=5000)
    updated_at: datetime


def validate_saved_cues(cues: list[SavedCue], duration_ms: int) -> None:
    previous = -1
    for index, cue in enumerate(cues):
        # Validate ranges even for disabled cues; never trust persisted JSON shape.
        if (
            cue.index != index
            or cue.start_ms < previous
            or cue.end_ms <= cue.start_ms
            or cue.end_ms > duration_ms
        ):
            raise ValueError("Invalid caption sequence")
        previous = cue.start_ms
