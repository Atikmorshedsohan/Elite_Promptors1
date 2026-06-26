"""Inbound payload schema. Validated by FastAPI before reaching the pipeline.

All required fields are explicit. Optional fields use `None` as the sentinel
default and are typed `T | None` so the contract is unambiguous.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

# --- Strict value sets (kept here, not in enums.py, because they are part of
# the WIRE FORMAT, not part of the response contract) ---

TransactionTypeLiteral = Literal[
    "send_money", "cash_out", "cash_in", "payment", "fee", "reversal", "deposit", "other"
]
TransactionStatusLiteral = Literal["success", "failed", "pending", "reversed"]
ChannelLiteral = Literal["app", "ussd", "web", "agent", "unknown"]

# Sane upper bound — protects the pipeline from absurd inputs.
MAX_AMOUNT_BDT: float = 10_000_000.0  # 1 crore


class Transaction(BaseModel):
    """A single normalized transaction row in the customer's history."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    transaction_id: str = Field(..., min_length=1, max_length=128)
    timestamp: datetime = Field(..., description="ISO-8601, UTC preferred")
    type: TransactionTypeLiteral
    amount: float = Field(..., gt=0.0, le=MAX_AMOUNT_BDT, description="Taka, positive")
    currency: str = Field(default="BDT", min_length=3, max_length=3)
    counterparty: str | None = Field(default=None, max_length=128)
    status: TransactionStatusLiteral = "success"
    reference: str | None = Field(default=None, max_length=128)
    description: str | None = Field(default=None, max_length=256)

    @field_validator("timestamp")
    @classmethod
    def _ts_tz_aware(cls, v: datetime) -> datetime:
        """Coerce naive datetimes to UTC; reject impossible values."""
        if v.tzinfo is None:
            v = v.replace(tzinfo=timezone.utc)
        return v.astimezone(timezone.utc)

    @field_validator("amount")
    @classmethod
    def _amount_round(cls, v: float) -> float:
        # Normalize to 2dp for downstream comparison.
        return round(float(v), 2)

    @field_validator("currency")
    @classmethod
    def _currency_upper(cls, v: str) -> str:
        return v.upper()

    def to_summary(self) -> dict[str, Any]:
        return {
            "transaction_id": self.transaction_id,
            "timestamp": self.timestamp.isoformat(),
            "type": self.type,
            "amount": self.amount,
            "currency": self.currency,
            "counterparty": self.counterparty,
            "status": self.status,
        }


class Metadata(BaseModel):
    """Request envelope metadata."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    ticket_id: str = Field(..., min_length=1, max_length=128)
    customer_id: str | None = Field(default=None, max_length=128)
    channel: ChannelLiteral = "unknown"
    locale: str = Field(default="en", min_length=2, max_length=5)
    submitted_at: datetime | None = None

    @field_validator("submitted_at")
    @classmethod
    def _submitted_at_tz(cls, v: datetime | None) -> datetime | None:
        if v is None:
            return None
        if v.tzinfo is None:
            v = v.replace(tzinfo=timezone.utc)
        return v.astimezone(timezone.utc)


class AnalyzeTicketRequest(BaseModel):
    """Top-level inbound payload for `POST /analyze-ticket`."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    complaint: str = Field(..., min_length=1, max_length=4000)
    transactions: list[Transaction] = Field(default_factory=list, max_length=200)
    metadata: Metadata

    @field_validator("complaint")
    @classmethod
    def _complaint_not_blank(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("complaint must not be blank")
        return v

    @model_validator(mode="after")
    def _tx_ids_unique(self) -> "AnalyzeTicketRequest":
        seen: set[str] = set()
        for t in self.transactions:
            if t.transaction_id in seen:
                raise ValueError(
                    f"duplicate transaction_id in payload: {t.transaction_id}"
                )
            seen.add(t.transaction_id)
        return self

    # ---- Convenience accessors used by services ----

    @property
    def ticket_id(self) -> str:
        return self.metadata.ticket_id

    @property
    def has_transactions(self) -> bool:
        return bool(self.transactions)