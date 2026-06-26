"""MatchResult — typed output of TransactionMatcherService.

Carries the chosen transaction, score (0.0–1.0), and the deterministic
reason codes that drove the pick. The EvidenceEngine consumes this.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from .request import Transaction
from .response import ReasonCodeLiteral

MatchMethodLiteral = Literal["rule_best", "rule_tie_llm_break", "rule_only", "no_match"]


class CandidateScore(BaseModel):
    """Score breakdown for a single candidate transaction."""

    model_config = ConfigDict(extra="forbid")

    transaction_id: str = Field(..., min_length=1, max_length=128)
    score: float = Field(..., ge=0.0, le=1.0)
    amount_score: float = Field(default=0.0, ge=0.0, le=1.0)
    date_score: float = Field(default=0.0, ge=0.0, le=1.0)
    type_score: float = Field(default=0.0, ge=0.0, le=1.0)
    counterparty_score: float = Field(default=0.0, ge=0.0, le=1.0)
    status_score: float = Field(default=0.0, ge=0.0, le=1.0)
    reason_codes: list[ReasonCodeLiteral] = Field(default_factory=list, max_length=10)

    @field_validator("reason_codes")
    @classmethod
    def _dedupe(cls, v: list[str]) -> list[str]:
        seen: set[str] = set()
        out: list[str] = []
        for c in v:
            if c not in seen:
                seen.add(c)
                out.append(c)
        return out


class MatchResult(BaseModel):
    """Strict matcher output."""

    model_config = ConfigDict(extra="forbid")

    matched: bool
    method: MatchMethodLiteral
    transaction: Transaction | None = None
    score: float = Field(default=0.0, ge=0.0, le=1.0)
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    top_candidates: list[CandidateScore] = Field(default_factory=list, max_length=5)
    reason_codes: list[ReasonCodeLiteral] = Field(default_factory=list, max_length=10)
    decided_at: datetime

    @field_validator("decided_at")
    @classmethod
    def _ts_tz(cls, v: datetime) -> datetime:
        if v.tzinfo is None:
            v = v.replace(tzinfo=timezone.utc)
        return v.astimezone(timezone.utc)

    @field_validator("reason_codes")
    @classmethod
    def _dedupe(cls, v: list[str]) -> list[str]:
        seen: set[str] = set()
        out: list[str] = []
        for c in v:
            if c not in seen:
                seen.add(c)
                out.append(c)
        return out

    def to_dict(self) -> dict[str, Any]:
        return self.model_dump(mode="json")


__all__ = ["MatchResult", "CandidateScore", "MatchMethodLiteral"]  # explicit export