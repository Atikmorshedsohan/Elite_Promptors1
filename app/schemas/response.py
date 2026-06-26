"""Final response contract. Single source of truth for the judges.

Every field here is required (unless explicitly `Optional`). The contract is
validated twice:
  1. Service layer constructs the model.
  2. Route handler re-validates before sending.
If validation fails on (2) the route returns a `degraded` envelope instead.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from .enums import (
    ActionEnum,
    CaseTypeEnum,
    DepartmentEnum,
    EvidenceVerdictEnum,
    SeverityEnum,
)

# --- Stable set of reason codes (machine-readable, snake_case) ---
ReasonCodeLiteral = Literal[
    "duplicate_within_window",
    "amount_matches_complaint",
    "amount_mismatch",
    "type_matches_intent",
    "type_mismatch",
    "date_within_window",
    "date_outside_window",
    "no_transactions_provided",
    "multiple_candidates_tied",
    "no_candidate_above_threshold",
    "complaint_contains_phishing_signal",
    "complaint_contains_unauthorized_signal",
    "complaint_contains_duplicate_signal",
    "complaint_contains_failed_signal",
    "high_value_dispute",
    "critical_value_dispute",
    "language_bangla",
    "language_banglish",
    "language_english",
    "prompt_injection_detected",
    "llm_timeout_fallback",
    "safety_violation_rewritten",
    "rule_override_of_llm",
]


class AnalyzeTicketResponse(BaseModel):
    """Strict response contract returned by `POST /analyze-ticket`."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    ticket_id: str = Field(..., min_length=1, max_length=128)

    # --- Evidence ---
    relevant_transaction_id: str | None = Field(
        default=None,
        max_length=128,
        description="ID of the most relevant transaction; null when insufficient_data.",
    )
    evidence_verdict: EvidenceVerdictEnum
    case_type: CaseTypeEnum
    department: DepartmentEnum
    severity: SeverityEnum

    # --- Decision ---
    human_review_required: bool
    confidence: float = Field(..., ge=0.0, le=1.0)
    reason_codes: list[ReasonCodeLiteral] = Field(default_factory=list, max_length=20)
    recommended_next_action: ActionEnum

    # --- Text ---
    agent_summary: str = Field(..., min_length=1, max_length=2000)
    customer_reply: str = Field(..., min_length=1, max_length=1000)

    # --- Diagnostics ---
    language_detected: Literal["en", "bn", "banglish", "unknown"] = "unknown"
    investigated_at: datetime
    schema_version: Literal["1.0"] = "1.0"

    @field_validator("investigated_at")
    @classmethod
    def _ts_tz(cls, v: datetime) -> datetime:
        if v.tzinfo is None:
            v = v.replace(tzinfo=timezone.utc)
        return v.astimezone(timezone.utc)

    @model_validator(mode="after")
    def _cross_field_invariants(self) -> "AnalyzeTicketResponse":
        # If there's no matched transaction the verdict MUST be insufficient_data.
        if self.relevant_transaction_id is None and self.evidence_verdict not in (
            EvidenceVerdictEnum.INSUFFICIENT_DATA,
        ):
            raise ValueError(
                "relevant_transaction_id must be set unless evidence_verdict is insufficient_data"
            )
        # Critical severity always requires human review.
        if self.severity == SeverityEnum.CRITICAL and not self.human_review_required:
            raise ValueError("critical severity must set human_review_required=True")
        return self

    # ---- Convenience ----

    def to_dict(self) -> dict[str, Any]:
        return self.model_dump(mode="json")