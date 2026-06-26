"""Agent summary prompt.

Internal-use narrative explaining the evidence and decision. Not shown
to the customer.
"""
from __future__ import annotations

import json

from ..schemas.enums import (
    CaseTypeEnum,
    DepartmentEnum,
    EvidenceVerdictEnum,
    SeverityEnum,
)


def build_summary_prompt(
    complaint: str,
    *,
    verdict: EvidenceVerdictEnum,
    case_type: CaseTypeEnum,
    department: DepartmentEnum,
    severity: SeverityEnum,
    relevant_txn_id: str | None,
    amount_taka: float | None,
    counterparty: str | None,
    reason_codes: list[str],
) -> str:
    """Compose the prompt for the internal agent summary."""
    payload = {
        "complaint": complaint.strip()[:1500],
        "verdict": verdict.value,
        "case_type": case_type.value,
        "department": department.value,
        "severity": severity.value,
        "relevant_txn_id": relevant_txn_id,
        "amount_taka": amount_taka,
        "counterparty": counterparty,
        "reason_codes": reason_codes,
    }
    return (
        "You are an internal-support summarizer. Produce a concise (max 6 "
        "sentences) agent-facing summary of the case based on the JSON below. "
        "Do not address the customer. Do not promise refunds, reversals, or "
        "unblocking. Do not ask for OTP, PIN, or passwords. Output plain "
        "text only — no JSON, no markdown.\n\n"
        f"CASE:\n{json.dumps(payload, ensure_ascii=False, indent=2)}"
    )


__all__ = ["build_summary_prompt"]