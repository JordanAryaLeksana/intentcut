"""Shared public error response contract."""

from pydantic import BaseModel


class ErrorResponse(BaseModel):
    code: str
    message: str
    file_index: int | None = None
