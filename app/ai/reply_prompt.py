"""Customer reply prompt.

Public-facing reply. Must obey safety rules — but the model can still emit
violations, so the SafetyGuard service re-scans this output.
"""
from __future__ import annotations

import json

from ..schemas.enums import (
    ActionEnum,
    DepartmentEnum,
    EvidenceVerdictEnum,
)


def build_reply_prompt(
    complaint: str,
    *,
    verdict: EvidenceVerdictEnum,
    department: DepartmentEnum,
    action: ActionEnum,
    language: str,
    relevant_txn_id: str | None,
) -> str:
    """Compose the prompt for the customer reply."""
    payload = {
        "complaint": complaint.strip()[:1500],
        "verdict": verdict.value,
        "department": department.value,
        "action": action.value,
        "language": language,
        "relevant_txn_id": relevant_txn_id,
    }
    return (
        "You write customer-facing replies for a fintech support service. "
        "Reply in the same language as the complaint. Be polite, neutral, "
        "and short (max 4 sentences). "
        "Hard rules you must obey:\n"
        "  • Never ask for OTP, PIN, password, seed phrase, CVV, or card number.\n"
        "  • Never promise a refund, reversal, recovery, or account unblock.\n"
        "  • Never direct the customer to a third-party link or app.\n"
        "  • If information is insufficient, say so and indicate the next step.\n"
        "Output plain text only — no JSON, no markdown.\n\n"
        f"CASE:\n{json.dumps(payload, ensure_ascii=False, indent=2)}\n\n"
        f"Reply (language={language}):"
    )


__all__ = ["build_reply_prompt"]