"""ComplaintInfo — the typed, validated output of ComplaintAnalyzerService."""
from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator

from .enums import IntentEnum, LanguageEnum, TransactionTypeEnum


class ComplaintInfo(BaseModel):
    """Strictly-typed result of complaint analysis.

    Built either from LLM output or from rule-based fallback. All enums are
    normalized to the canonical value sets — the service layer guarantees this.
    """

    model_config = ConfigDict(extra="forbid")

    raw_text: str = Field(..., min_length=1, max_length=4000)
    language: LanguageEnum = LanguageEnum.UNKNOWN

    intent: IntentEnum = IntentEnum.UNKNOWN
    transaction_type: TransactionTypeEnum | None = None

    amount_bdt: float | None = Field(default=None, gt=0.0, le=10_000_000.0)
    counterparty: str | None = Field(default=None, max_length=128)
    phone_numbers: list[str] = Field(default_factory=list, max_length=10)
    merchant_refs: list[str] = Field(default_factory=list, max_length=10)

    time_hint: datetime | None = None
    issue_keywords: list[str] = Field(default_factory=list, max_length=30)
    refund_intent: bool = False
    fraud_indicators: list[str] = Field(default_factory=list, max_length=10)
    urgency_signals: list[str] = Field(default_factory=list, max_length=10)

    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    source: str = Field(default="rules", description="rules | llm | hybrid")

    @field_validator("phone_numbers", "merchant_refs", "issue_keywords",
                     "fraud_indicators", "urgency_signals")
    @classmethod
    def _strip_lower(cls, v: list[str]) -> list[str]:
        out: list[str] = []
        for item in v:
            if not isinstance(item, str):
                continue
            s = item.strip()
            if s and s not in out:
                out.append(s.lower() if not s.startswith("+") else s)
        return out

    @field_validator("counterparty")
    @classmethod
    def _counterparty_clean(cls, v: str | None) -> str | None:
        if v is None:
            return None
        s = v.strip()
        return s or None

    @field_validator("time_hint")
    @classmethod
    def _time_hint_tz(cls, v: datetime | None) -> datetime | None:
        if v is None:
            return None
        from datetime import timezone
        if v.tzinfo is None:
            v = v.replace(tzinfo=timezone.utc)
        return v.astimezone(timezone.utc)

    def has_amount(self) -> bool:
        return self.amount_bdt is not None

    def has_counterparty(self) -> bool:
        return bool(self.counterparty) or bool(self.phone_numbers)

    def to_dict(self) -> dict[str, Any]:
        return self.model_dump(mode="json")


__all__ = ["ComplaintInfo"]  # explicit export