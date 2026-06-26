"""GET /health — liveness + readiness."""
from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter
from pydantic import BaseModel, ConfigDict, Field

router = APIRouter(tags=["health"])


class HealthResponse(BaseModel):
    """Strict health envelope."""

    model_config = ConfigDict(extra="forbid")

    status: str = Field(..., description="ok | degraded | down")
    service: str = Field(default="ticket-investigator")
    version: str = Field(default="1.0.0")
    timestamp: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc)
    )

    def to_dict(self) -> dict:
        return self.model_dump(mode="json")


@router.get("/health", response_model=HealthResponse)
def health() -> HealthResponse:
    """Liveness probe. Always returns 200 OK unless the process is dead."""
    return HealthResponse(status="ok")


__all__ = ["health", "HealthResponse"]
