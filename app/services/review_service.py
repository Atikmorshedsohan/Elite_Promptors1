"""Review service: produce the human-review ticket payload.

The review ticket is the structured handoff a human agent will see
inside their CRM. It must contain enough context to begin work
without needing to re-query any system:
    - priority (derived from severity)
    - queue (the action's lane + the action itself)
    - subject (one-line summary)
    - context (the classification + routing rationale)
    - conversation (the original complaint verbatim)
    - suggested_reply (the SafetyService-sanitized draft, if any)
    - reason_codes (full audit trail)

A ticket is generated whenever the classifier asked for human review,
OR when the routing action is escalation-grade. Otherwise the
service still produces one but flags it as `priority="P5"`.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.enums import (
    ActionEnum,
    DepartmentEnum,
    OfficialCaseTypeEnum,
    SeverityEnum,
)
from app.utils.logger import get_logger

_logger = get_logger(__name__)


# --- Priority bands ---

_SEVERITY_TO_PRIORITY: dict[SeverityEnum, str] = {
    SeverityEnum.CRITICAL: "P1",
    SeverityEnum.HIGH: "P2",
    SeverityEnum.MEDIUM: "P3",
    SeverityEnum.LOW: "P4",
}

# Actions that ALWAYS require human eyes on the ticket, regardless of
# the classifier's `needs_human_review` flag.
_FORCE_HUMAN_ACTIONS: frozenset[ActionEnum] = frozenset({
    ActionEnum.ESCALATE_TO_AGENT,
    ActionEnum.ROUTE_TO_FRAUD,
    ActionEnum.ROUTE_TO_DISPUTES,
})


class ReviewTicket(BaseModel):
    """The structured handoff a human agent sees in their CRM."""

    model_config = ConfigDict(extra="forbid")

    ticket_id: str = Field(..., min_length=1, max_length=128)
    priority: str = Field(..., description="P1 (critical) .. P5 (info)")
    queue: str = Field(..., min_length=1, max_length=64)
    subject: str = Field(..., min_length=1, max_length=200)
    context: dict[str, Any] = Field(default_factory=dict)
    conversation: list[dict[str, str]] = Field(default_factory=list)
    suggested_reply: str | None = None
    reason_codes: list[str] = Field(default_factory=list, max_length=32)
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc)
    )


class ReviewService:
    """Stateless — every call is independent."""

    def build(
        self,
        *,
        ticket_id: str,
        customer_id: str | None,
        complaint_text: str,
        department: DepartmentEnum,
        severity: SeverityEnum,
        case_type: OfficialCaseTypeEnum,
        action: ActionEnum,
        reason_codes: list[str],
        suggested_reply: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> ReviewTicket:
        priority = _SEVERITY_TO_PRIORITY.get(severity, "P5")
        needs_human = action in _FORCE_HUMAN_ACTIONS or priority in ("P1", "P2")
        if not needs_human:
            priority = "P5"  # informational only

        queue = f"{department.value}:{action.value}"
        subject = _build_subject(case_type, severity, action)

        context: dict[str, Any] = {
            "department": department.value,
            "severity": severity.value,
            "case_type": case_type.value,
            "action": action.value,
            "priority": priority,
            "needs_human_review": needs_human,
        }
        if customer_id is not None:
            context["customer_id"] = customer_id
        if metadata:
            # Surface only safe, explicitly-passed fields
            for k in ("channel", "locale", "submitted_at"):
                if k in metadata:
                    context[k] = metadata[k]

        conversation: list[dict[str, str]] = [
            {
                "role": "customer",
                "message": complaint_text,
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }
        ]

        full_reasons = list(reason_codes)
        if needs_human:
            full_reasons.append("review_ticket_generated")

        _logger.info(
            "review_ticket_built",
            extra={
                "ticket_id": ticket_id,
                "priority": priority,
                "queue": queue,
                "action": action.value,
                "needs_human": needs_human,
            },
        )

        return ReviewTicket(
            ticket_id=ticket_id,
            priority=priority,
            queue=queue,
            subject=subject,
            context=context,
            conversation=conversation,
            suggested_reply=suggested_reply,
            reason_codes=full_reasons,
        )


def _build_subject(
    case_type: OfficialCaseTypeEnum,
    severity: SeverityEnum,
    action: ActionEnum,
) -> str:
    """One-line CRM subject line, prefixed by severity for fast triage."""
    prefix = f"[{severity.value.upper()}]"
    label_map = {
        OfficialCaseTypeEnum.WRONG_TRANSFER: "Wrong transfer reported",
        OfficialCaseTypeEnum.PAYMENT_FAILED: "Failed payment / transfer",
        OfficialCaseTypeEnum.REFUND_REQUEST: "Refund requested",
        OfficialCaseTypeEnum.DUPLICATE_PAYMENT: "Duplicate debit reported",
        OfficialCaseTypeEnum.MERCHANT_SETTLEMENT_DELAY: "Merchant settlement delay",
        OfficialCaseTypeEnum.AGENT_CASH_IN_ISSUE: "Agent cash-in issue",
        OfficialCaseTypeEnum.PHISHING_OR_SOCIAL_ENGINEERING:
            "Phishing / social engineering report",
        OfficialCaseTypeEnum.OTHER: "General inquiry",
    }
    base = label_map.get(case_type, "Customer ticket")
    return f"{prefix} {base} → {action.value}"
