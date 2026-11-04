from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

PIPELINE = "image_generate_v1"


class VisualRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    request_id: UUID
    prompt: str = Field(min_length=1, max_length=2000)
    preset: Literal["thumbnail", "cover", "poster"] = "thumbnail"
    operation: Literal["generate", "edit"] = "generate"
    source_artifact_id: UUID | None = None
    frame_seconds: float | None = Field(
        default=None, ge=0, le=600, allow_inf_nan=False, strict=True
    )

    @model_validator(mode="after")
    def valid(self):
        if not self.prompt.strip() or "\x00" in self.prompt:
            raise ValueError("Describe the image")
        if (self.operation == "edit") != (self.source_artifact_id is not None):
            raise ValueError("Editing requires an authorized source")
        if self.operation == "generate" and self.frame_seconds is not None:
            raise ValueError("Generation cannot select a frame")
        return self
    name: str | None = Field(default=None, min_length=1, max_length=80)

    @field_validator("name")
    @classmethod
    def validate_name(cls, value: str | None) -> str | None:
        if value is None:
            return None
        name = value.strip()
        if not name or not name.isprintable():
            raise ValueError("Enter a valid image name")
        return name


class CoverRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    artifact_id: UUID
    expected_revision: int = Field(ge=0, strict=True)

class RenameImageRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=1, max_length=80)

    @field_validator("name")
    @classmethod
    def validate_name(cls, value: str) -> str:
        name = value.strip()
        if not name or not name.isprintable():
            raise ValueError("Enter a valid image name")
        return name