"""First-cut inputs shared by HTTP admission and worker processing."""

from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class FirstCutRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    kind: Literal["first_cut"]
    intent: str = Field(min_length=1, max_length=1000)
    target_seconds: float = Field(gt=0, le=120, allow_inf_nan=False, strict=True)
    media_ids: list[UUID] = Field(min_length=1, max_length=10)

    @field_validator("media_ids")
    @classmethod
    def unique_media(cls, value: list[UUID]) -> list[UUID]:
        if len(value) != len(set(value)):
            raise ValueError("Media IDs must be unique")
        return value


class UploadedFirstCutRequest(FirstCutRequest):
    """Server-only persisted contract; HTTP clients cannot supply fingerprints."""

    pipeline_version: Literal["uploaded_v1"]
    source_sha256: dict[str, str] = Field(min_length=1, max_length=10)

    @model_validator(mode="after")
    def valid_fingerprints(self) -> "UploadedFirstCutRequest":
        if set(self.source_sha256) != {str(media_id) for media_id in self.media_ids}:
            raise ValueError("Source fingerprint membership mismatch")
        for digest in self.source_sha256.values():
            if len(digest) != 64 or any(c not in "0123456789abcdef" for c in digest):
                raise ValueError("Invalid source fingerprint")
        return self
