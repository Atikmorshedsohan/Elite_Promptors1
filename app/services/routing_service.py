"""Routing service: classification + evidence → next-best action.

Thin orchestrator over `app.rules.routing_rules.route`. Adds:
    - audit timestamp
    - logger trace
    - typed `RoutingDecision` envelope
"""
from __future__ import annotations

from datetime import datetime, timezone

from pydantic import BaseModel, ConfigDict, Field

from app.rules.routing_rules import route
from app.schemas.enums import (
    ActionEnum,
    DepartmentEnum,
    OfficialCaseTypeEnum,
    SeverityEnum,
)
from app.utils.logger import get_logger

_logger = get_logger(__name__)


class RoutingDecision(BaseModel):
    """The action the investigation pipeline should take next.

    `reason_codes` is an ordered audit trail: base action first, then
    any escalation triggers (severity, human-review).
    """

    model_config = ConfigDict(extra="forbid")

    action: ActionEnum
    department: DepartmentEnum
    severity: SeverityEnum
    case_type: OfficialCaseTypeEnum
    needs_human_review: bool
    reason_codes: list[str] = Field(default_factory=list, max_length=16)
    decided_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc)
    )


class RoutingService:
    """Stateless — every call is independent."""

    def decide(
        self,
        *,
        department: DepartmentEnum,
        severity: SeverityEnum,
        case_type: OfficialCaseTypeEnum,
        needs_human_review: bool,
    ) -> RoutingDecision:
        action, reason_codes = route(
            department=department,
            severity=severity,
            case_type=case_type,
            needs_human_review=needs_human_review,
        )

        _logger.info(
            "routing_decision",
            extra={
                "action": action.value,
                "department": department.value,
                "severity": severity.value,
                "case_type": case_type.value,
                "needs_human_review": needs_human_review,
                "reason_codes": reason_codes,
            },
        )

        return RoutingDecision(
            action=action,
            department=department,
            severity=severity,
            case_type=case_type,
            needs_human_review=needs_human_review,
            reason_codes=reason_codes,
        )
