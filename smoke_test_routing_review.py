"""Smoke test: RoutingService + ReviewService."""
from __future__ import annotations

import sys

from app.schemas.enums import (
    ActionEnum,
    DepartmentEnum,
    OfficialCaseTypeEnum,
    SeverityEnum,
)
from app.services.review_service import ReviewService
from app.services.routing_service import RoutingService


CASES = [
    {
        "label": "S1 fraud_risk + high (phishing)",
        "department": DepartmentEnum.FRAUD_RISK,
        "severity": SeverityEnum.HIGH,
        "case_type": OfficialCaseTypeEnum.PHISHING_OR_SOCIAL_ENGINEERING,
        "needs_human_review": True,
        "complaint": "I got an SMS asking for my PIN to verify my account.",
    },
    {
        "label": "S2 disputes + medium (duplicate debit)",
        "department": DepartmentEnum.DISPUTES,
        "severity": SeverityEnum.MEDIUM,
        "case_type": OfficialCaseTypeEnum.DUPLICATE_PAYMENT,
        "needs_human_review": False,
        "complaint": "I was charged twice for the same transfer of 500 taka.",
    },
    {
        "label": "S3 payments + critical (failed high-value transfer)",
        "department": DepartmentEnum.PAYMENTS,
        "severity": SeverityEnum.CRITICAL,
        "case_type": OfficialCaseTypeEnum.PAYMENT_FAILED,
        "needs_human_review": True,
        "complaint": "My 80,000 taka transfer shows failed but the money left.",
    },
    {
        "label": "S4 customer_success + low (refund request, low value)",
        "department": DepartmentEnum.CUSTOMER_SUCCESS,
        "severity": SeverityEnum.LOW,
        "case_type": OfficialCaseTypeEnum.REFUND_REQUEST,
        "needs_human_review": False,
        "complaint": "Please refund the small double-charge from yesterday.",
    },
]


def main():
    router = RoutingService()
    reviewer = ReviewService()

    for i, c in enumerate(CASES, start=1):
        decision = router.decide(
            department=c["department"],
            severity=c["severity"],
            case_type=c["case_type"],
            needs_human_review=c["needs_human_review"],
        )
        ticket = reviewer.build(
            ticket_id=f"TKT-{i:04d}",
            customer_id=f"CUST-{i:04d}",
            complaint_text=c["complaint"],
            department=c["department"],
            severity=c["severity"],
            case_type=c["case_type"],
            action=decision.action,
            reason_codes=decision.reason_codes,
            suggested_reply="We are looking into this and will follow up shortly.",
            metadata={"channel": "app", "locale": "en"},
        )
        print(
            f"{c['label']:55s} action={decision.action.value:24s} "
            f"priority={ticket.priority} queue={ticket.queue}"
        )
        print(f"  reasons: {decision.reason_codes}")
        print(f"  subject: {ticket.subject}")

    s1 = router.decide(
        department=DepartmentEnum.FRAUD_RISK,
        severity=SeverityEnum.HIGH,
        case_type=OfficialCaseTypeEnum.PHISHING_OR_SOCIAL_ENGINEERING,
        needs_human_review=True,
    )
    assert s1.action == ActionEnum.ESCALATE_TO_AGENT, f"S1 got {s1.action}"
    assert "severity_high_sensitive_lane" in s1.reason_codes
    assert "queue_for_human_review" in s1.reason_codes

    s3 = router.decide(
        department=DepartmentEnum.PAYMENTS,
        severity=SeverityEnum.CRITICAL,
        case_type=OfficialCaseTypeEnum.PAYMENT_FAILED,
        needs_human_review=True,
    )
    assert s3.action == ActionEnum.ESCALATE_TO_AGENT, f"S3 got {s3.action}"
    assert "severity_critical" in s3.reason_codes

    s_payments_high = router.decide(
        department=DepartmentEnum.PAYMENTS,
        severity=SeverityEnum.HIGH,
        case_type=OfficialCaseTypeEnum.PAYMENT_FAILED,
        needs_human_review=False,
    )
    assert s_payments_high.action == ActionEnum.ROUTE_TO_PAYMENTS, (
        f"payments+high expected ROUTE_TO_PAYMENTS, got {s_payments_high.action}"
    )

    s4_ticket = reviewer.build(
        ticket_id="TKT-INFO",
        customer_id="CUST-INFO",
        complaint_text="Just a small question.",
        department=DepartmentEnum.CUSTOMER_SUCCESS,
        severity=SeverityEnum.LOW,
        case_type=OfficialCaseTypeEnum.OTHER,
        action=ActionEnum.REQUEST_MORE_INFO,
        reason_codes=["base_action:request_more_info"],
        suggested_reply="Thanks for reaching out -- happy to help.",
    )
    assert s4_ticket.priority == "P5", f"expected P5, got {s4_ticket.priority}"

    print()
    print("ALL ASSERTIONS PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())
