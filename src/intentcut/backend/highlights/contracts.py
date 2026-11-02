"""Highlight admission contracts: additive, backward-compatible, server-owned."""

import re
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

_CANDIDATE_ID = re.compile(r"hl-\d{2}")


class HighlightRequest(BaseModel):
    """GUIDED when intent names an editorial goal; AUTO when intent is generic."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    kind: Literal["highlight"]
    intent: str = Field(min_length=1, max_length=1000)
    target_seconds: float = Field(gt=0, le=120, allow_inf_nan=False, strict=True)
    media_ids: list[UUID] = Field(min_length=1, max_length=1)
    candidate_seconds: float = Field(
        default=8.0, gt=0, le=30, allow_inf_nan=False, strict=True
    )
    max_candidates: int = Field(default=8, ge=1, le=12, strict=True)
    candidate_ids: list[str] | None = Field(default=None, max_length=12)

    @field_validator("candidate_ids")
    @classmethod
    def valid_candidate_ids(cls, value: list[str] | None) -> list[str] | None:
        if value is None:
            return None
        if not value or len(value) != len(set(value)):
            raise ValueError("Candidate selection must list unique IDs")
        if any(_CANDIDATE_ID.fullmatch(item) is None for item in value):
            raise ValueError("Invalid candidate ID")
        return value


class UploadedHighlightRequest(HighlightRequest):
    """Server-only persisted contract; HTTP clients cannot supply fingerprints."""

    pipeline_version: Literal["highlight_v1"]
    source_sha256: dict[str, str] = Field(min_length=1, max_length=1)

    @model_validator(mode="after")
    def valid_fingerprints(self) -> "UploadedHighlightRequest":
        if set(self.source_sha256) != {str(media_id) for media_id in self.media_ids}:
            raise ValueError("Source fingerprint membership mismatch")
        for digest in self.source_sha256.values():
            if len(digest) != 64 or any(c not in "0123456789abcdef" for c in digest):
                raise ValueError("Invalid source fingerprint")
        return self


class CandidateResponse(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    id: str
    media_id: UUID
    start_seconds: float
    end_seconds: float
    score: float
    components: dict[str, float]
    heuristic_only: Literal[True] = True


class CandidateListResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    media_id: UUID
    duration_seconds: float
    sha256: str
    candidates: list[CandidateResponse] = Field(max_length=12)
