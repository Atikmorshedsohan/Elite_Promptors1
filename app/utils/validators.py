"""Pydantic helpers shared across services."""
from __future__ import annotations

from pydantic import BaseModel, Field


class ConfidenceField(BaseModel):
    """Mixin to enforce confidence in [0, 1]."""

    confidence: float = Field(..., ge=0.0, le=1.0)


__all__ = ["ConfidenceField"]  # placeholder for future shared mixins