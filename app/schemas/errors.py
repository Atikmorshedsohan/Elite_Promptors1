"""Schema-consistent error envelopes."""
from __future__ import annotations

from pydantic import BaseModel, Field


class ErrorDetail(BaseModel):
    code: str = Field(..., description="Machine-readable error code")
    message: str = Field(..., description="Human-readable error message")
    field: str | None = Field(default=None, description="Field that caused the error")


class ErrorEnvelope(BaseModel):
    error: ErrorDetail