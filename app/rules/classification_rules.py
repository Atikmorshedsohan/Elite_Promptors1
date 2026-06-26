"""Classification rule helpers.

Pure functions mapping `(intent, verdict, txn_type, fraud_signal)` →
`OfficialCaseTypeEnum`. No I/O. No LLM.
"""
from __future__ import annotations

from ..schemas.enums import (
    CaseTypeEnum,
    EvidenceVerdictEnum,
    IntentEnum,
    OfficialCaseTypeEnum,
    TransactionTypeEnum,
)


def classify(
    intent: IntentEnum | str,
    verdict: EvidenceVerdictEnum | str,
    txn_type: TransactionTypeEnum | str | None = None,
    has_fraud_signal: bool = False,
    counterparty_is_agent: bool = False,
) -> OfficialCaseTypeEnum:
    """Return the official case-type label for the case."""
    intent_v = intent.value if isinstance(intent, IntentEnum) else str(intent)
    verdict_v = verdict.value if isinstance(verdict, EvidenceVerdictEnum) else str(verdict)
    txn_v = txn_type.value if isinstance(txn_type, TransactionTypeEnum) else (
        str(txn_type) if txn_type else None
    )

    # 1. Fraud signal always wins → phishing/social engineering.
    if has_fraud_signal or intent_v == IntentEnum.PHISHING_REPORT.value:
        return OfficialCaseTypeEnum.PHISHING_OR_SOCIAL_ENGINEERING

    # 2. Duplicate / double charge.
    if intent_v == IntentEnum.DUPLICATE_DEBIT.value:
        return OfficialCaseTypeEnum.DUPLICATE_PAYMENT
    if verdict_v == EvidenceVerdictEnum.CONSISTENT.value and intent_v == IntentEnum.REFUND_REQUEST.value:
        # Duplicate-style refund after a confirmed debit still maps to duplicate.
        if txn_v in {TransactionTypeEnum.SEND_MONEY.value, TransactionTypeEnum.PAYMENT.value}:
            return OfficialCaseTypeEnum.DUPLICATE_PAYMENT

    # 3. Failed transfer / payment.
    if intent_v == IntentEnum.FAILED_TRANSFER.value or verdict_v == EvidenceVerdictEnum.INCONSISTENT.value:
        if txn_v == TransactionTypeEnum.PAYMENT.value:
            return OfficialCaseTypeEnum.MERCHANT_SETTLEMENT_DELAY
        if counterparty_is_agent:
            return OfficialCaseTypeEnum.AGENT_CASH_IN_ISSUE
        return OfficialCaseTypeEnum.PAYMENT_FAILED

    # 4. Unauthorized / wrong transfer.
    if intent_v == IntentEnum.UNAUTHORIZED_TRANSACTION.value:
        return OfficialCaseTypeEnum.WRONG_TRANSFER

    # 5. Refund requests.
    if intent_v == IntentEnum.REFUND_REQUEST.value:
        return OfficialCaseTypeEnum.REFUND_REQUEST

    # 6. Insufficient data → OTHER.
    if verdict_v == EvidenceVerdictEnum.INSUFFICIENT_DATA.value:
        return OfficialCaseTypeEnum.OTHER

    # 7. Fallback.
    return OfficialCaseTypeEnum.OTHER


# --- Department routing -----------------------------------------------------

_DEPARTMENT_MAP: dict[OfficialCaseTypeEnum, str] = {
    OfficialCaseTypeEnum.WRONG_TRANSFER.value: "disputes",
    OfficialCaseTypeEnum.PAYMENT_FAILED.value: "payments",
    OfficialCaseTypeEnum.REFUND_REQUEST.value: "disputes",
    OfficialCaseTypeEnum.DUPLICATE_PAYMENT.value: "disputes",
    OfficialCaseTypeEnum.MERCHANT_SETTLEMENT_DELAY.value: "payments",
    OfficialCaseTypeEnum.AGENT_CASH_IN_ISSUE.value: "payments",
    OfficialCaseTypeEnum.PHISHING_OR_SOCIAL_ENGINEERING.value: "fraud_risk",
    OfficialCaseTypeEnum.OTHER.value: "customer_success",
}


def department_for(case_type: OfficialCaseTypeEnum | str) -> str:
    key = case_type.value if isinstance(case_type, OfficialCaseTypeEnum) else str(case_type)
    return _DEPARTMENT_MAP.get(key, "customer_success")


# --- Severity prediction ----------------------------------------------------

def severity_for(
    case_type: OfficialCaseTypeEnum | str,
    amount_bdt: float | None,
    verdict: EvidenceVerdictEnum | str,
    has_fraud_signal: bool,
    *,
    high_value_threshold: float,
    critical_value_threshold: float,
) -> str:
    """Return 'low' | 'medium' | 'high' | 'critical'."""
    key = case_type.value if isinstance(case_type, OfficialCaseTypeEnum) else str(case_type)
    verdict_v = verdict.value if isinstance(verdict, EvidenceVerdictEnum) else str(verdict)

    base = {
        OfficialCaseTypeEnum.PHISHING_OR_SOCIAL_ENGINEERING.value: "high",
        OfficialCaseTypeEnum.WRONG_TRANSFER.value: "high",
        OfficialCaseTypeEnum.DUPLICATE_PAYMENT.value: "medium",
        OfficialCaseTypeEnum.PAYMENT_FAILED.value: "medium",
        OfficialCaseTypeEnum.REFUND_REQUEST.value: "medium",
        OfficialCaseTypeEnum.MERCHANT_SETTLEMENT_DELAY.value: "medium",
        OfficialCaseTypeEnum.AGENT_CASH_IN_ISSUE.value: "medium",
        OfficialCaseTypeEnum.OTHER.value: "low",
    }.get(key, "low")

    # Value bump.
    if amount_bdt is not None:
        if amount_bdt >= critical_value_threshold:
            base = "critical"
        elif amount_bdt >= high_value_threshold and base in {"medium", "low"}:
            base = "high"

    # Insufficient data → at least medium.
    if verdict_v == EvidenceVerdictEnum.INSUFFICIENT_DATA.value and base == "low":
        base = "medium"

    # Fraud always at least high.
    if has_fraud_signal and base in {"low", "medium"}:
        base = "high"

    return base


# --- Human review decision --------------------------------------------------

def needs_human_review(
    severity: str,
    verdict: EvidenceVerdictEnum | str,
    confidence: float,
    *,
    min_confidence: float,
) -> bool:
    """Boolean: true if the case must be reviewed by a human agent."""
    verdict_v = verdict.value if isinstance(verdict, EvidenceVerdictEnum) else str(verdict)
    if severity in {"high", "critical"}:
        return True
    if verdict_v == EvidenceVerdictEnum.INSUFFICIENT_DATA.value:
        return True
    if confidence < min_confidence:
        return True
    return False


# --- Backward-compatible alias ---------------------------------------------

__all__ = [
    "classify",
    "department_for",
    "severity_for",
    "needs_human_review",
    "_DEPARTMENT_MAP",
]  # explicit export