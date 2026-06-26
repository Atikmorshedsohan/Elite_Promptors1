"""Pure routing decision logic.

Maps (DepartmentEnum, SeverityEnum, case_type, needs_human_review) ->
ActionEnum. Pure function -- no I/O, no LLM, fully unit-testable.

The action vocabulary follows `ActionEnum` in `app.schemas.enums`:
    ROUTE_TO_DISPUTES, ROUTE_TO_FRAUD, ROUTE_TO_PAYMENTS,
    ROUTE_TO_CUSTOMER_SUCCESS, ROUTE_TO_TECHNICAL,
    ESCALATE_TO_AGENT, REQUEST_MORE_INFO, NO_ACTION_REQUIRED

Severity escalation:
    - critical severity ALWAYS escalates to ESCALATE_TO_AGENT
    - high severity + sensitive lane (fraud / agent) escalates
    - needs_human_review is recorded as a reason code but does not
      change the underlying action -- the review-service payload picks
      it up downstream.
"""
from __future__ import annotations

from app.schemas.enums import (
    ActionEnum,
    DepartmentEnum,
    OfficialCaseTypeEnum,
    SeverityEnum,
)


# --- Base department -> action mapping ---

_DEPARTMENT_BASE_ACTION: dict[DepartmentEnum, ActionEnum] = {
    DepartmentEnum.FRAUD_RISK: ActionEnum.ROUTE_TO_FRAUD,
    DepartmentEnum.DISPUTES: ActionEnum.ROUTE_TO_DISPUTES,
    DepartmentEnum.PAYMENTS: ActionEnum.ROUTE_TO_PAYMENTS,
    DepartmentEnum.CUSTOMER_SUCCESS: ActionEnum.ROUTE_TO_CUSTOMER_SUCCESS,
    DepartmentEnum.TECHNICAL_SUPPORT: ActionEnum.ROUTE_TO_TECHNICAL,
}


# --- Case-type overrides (case-type trumps department default when more
# specific). Used to e.g. send phishing straight to fraud even if the
# department classifier mis-grouped it. ---

_CASE_TYPE_OVERRIDES: dict[OfficialCaseTypeEnum, ActionEnum] = {
    OfficialCaseTypeEnum.PHISHING_OR_SOCIAL_ENGINEERING:
        ActionEnum.ROUTE_TO_FRAUD,
    OfficialCaseTypeEnum.DUPLICATE_PAYMENT: ActionEnum.ROUTE_TO_DISPUTES,
    OfficialCaseTypeEnum.WRONG_TRANSFER: ActionEnum.ROUTE_TO_DISPUTES,
    OfficialCaseTypeEnum.PAYMENT_FAILED: ActionEnum.ROUTE_TO_PAYMENTS,
    OfficialCaseTypeEnum.REFUND_REQUEST: ActionEnum.ROUTE_TO_DISPUTES,
    OfficialCaseTypeEnum.AGENT_CASH_IN_ISSUE: ActionEnum.ESCALATE_TO_AGENT,
    OfficialCaseTypeEnum.MERCHANT_SETTLEMENT_DELAY:
        ActionEnum.ROUTE_TO_PAYMENTS,
    OfficialCaseTypeEnum.OTHER: ActionEnum.REQUEST_MORE_INFO,
}

# Sensitive lanes that may escalate on HIGH severity.
_SENSITIVE_LANES: frozenset[ActionEnum] = frozenset({
    ActionEnum.ROUTE_TO_FRAUD,
    ActionEnum.ESCALATE_TO_AGENT,
})


def base_action_for(
    department: DepartmentEnum,
    case_type: OfficialCaseTypeEnum,
) -> ActionEnum:
    """Pick the base action. Case-type overrides win when present."""
    return _CASE_TYPE_OVERRIDES.get(
        case_type, _DEPARTMENT_BASE_ACTION[department]
    )


def apply_severity_escalation(
    action: ActionEnum,
    severity: SeverityEnum,
) -> tuple[ActionEnum, str | None]:
    """Bump the action based on severity.

    Returns (possibly-escalated-action, escalation-reason-or-None).
    """
    if severity == SeverityEnum.CRITICAL:
        return ActionEnum.ESCALATE_TO_AGENT, "severity_critical"
    if severity == SeverityEnum.HIGH and action in _SENSITIVE_LANES:
        return ActionEnum.ESCALATE_TO_AGENT, "severity_high_sensitive_lane"
    return action, None


def apply_human_review_flag(
    needs_human_review: bool,
) -> str | None:
    """Surface the human-review request as a reason code, no action change."""
    return "queue_for_human_review" if needs_human_review else None


def route(
    department: DepartmentEnum,
    severity: SeverityEnum,
    case_type: OfficialCaseTypeEnum,
    needs_human_review: bool,
) -> tuple[ActionEnum, list[str]]:
    """Compose the final action and ordered reason-code list.

    Order: base action -> severity escalation -> human-review flag.
    """
    reason_codes: list[str] = []

    base = base_action_for(department, case_type)
    reason_codes.append(f"base_action:{base.value}")

    action, esc_reason = apply_severity_escalation(base, severity)
    if esc_reason is not None:
        reason_codes.append(esc_reason)

    hr_reason = apply_human_review_flag(needs_human_review)
    if hr_reason is not None:
        reason_codes.append(hr_reason)

    return action, reason_codes
