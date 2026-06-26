"""Evidence evaluation rules.

Pure deterministic functions that look at (ComplaintInfo, MatchResult) and
produce an `EvidenceVerdictEnum` plus a calibrated confidence and a list of
machine-readable reason codes.

No I/O. No LLM. No time-of-day dependencies (other than `datetime.now()` for
the `decided_at` stamp which lives on the service layer).

Three verdicts:
    CONSISTENT         — best candidate matches the complaint intent + amount + type
    INCONSISTENT       — best candidate exists but contradicts the complaint
    INSUFFICIENT_DATA  — no candidate above threshold OR complaint lacks details
"""
from __future__ import annotations

from typing import Iterable

from ..schemas.complaint_info import ComplaintInfo
from ..schemas.enums import (
    EvidenceVerdictEnum,
    IntentEnum,
    TransactionTypeEnum,
)
from ..schemas.match_result import MatchResult

# --- Tunable thresholds (override at call sites if needed) ----------------

HIGH_VALUE_TAKA = 5_000.0        # above this, an amount match weighs more
AMOUNT_TOLERANCE_PCT = 0.05      # ±5 % tolerance for "amount matches"
MIN_MATCH_CONFIDENCE = 0.55      # below this we consider it "no candidate"


# --- Helpers ---------------------------------------------------------------

def _intent_for_txn_type(txn_type: TransactionTypeEnum | str | None) -> set[str]:
    """Return the set of intents a transaction type plausibly supports."""
    if txn_type is None:
        return set()
    v = txn_type.value if isinstance(txn_type, TransactionTypeEnum) else str(txn_type)
    return {
        "send_money": {IntentEnum.DUPLICATE_DEBIT.value, IntentEnum.UNAUTHORIZED_TRANSACTION.value},
        "cash_out": {IntentEnum.UNAUTHORIZED_TRANSACTION.value},
        # cash_in has no dedicated intent; route to GENERAL_INQUIRY (intent) while
        # the case-type layer surfaces OfficialCaseTypeEnum.AGENT_CASH_IN_ISSUE.
        "cash_in": {IntentEnum.GENERAL_INQUIRY.value, IntentEnum.UNAUTHORIZED_TRANSACTION.value},
        "payment": {IntentEnum.FAILED_TRANSFER.value, IntentEnum.REFUND_REQUEST.value,
                    IntentEnum.DUPLICATE_DEBIT.value},
        "fee": set(),
        "reversal": set(),
        "deposit": set(),
        "other": set(),
    }.get(v, set())


def _has_fraud_signal(complaint: ComplaintInfo) -> bool:
    return bool(complaint.fraud_indicators) or complaint.intent == IntentEnum.PHISHING_REPORT


# --- Main entry ------------------------------------------------------------

def evaluate(
    complaint: ComplaintInfo,
    match: MatchResult,
    *,
    amount_tolerance_pct: float = AMOUNT_TOLERANCE_PCT,
    min_match_confidence: float = MIN_MATCH_CONFIDENCE,
) -> tuple[EvidenceVerdictEnum, float, list[str]]:
    """Return (verdict, calibrated_confidence, reason_codes)."""
    reasons: list[str] = []
    confidence = max(0.0, min(1.0, match.confidence))

    # --- 0. No candidate at all → insufficient ----------------------------
    if not match.matched or not match.top_candidates:
        reasons.append("no_candidate_above_threshold")
        return EvidenceVerdictEnum.INSUFFICIENT_DATA, min(confidence, 0.3), reasons

    # --- 1. Pick the top candidate --------------------------------------
    top = match.top_candidates[0]
    txn_type_str = top.transaction_type if hasattr(top, "transaction_type") else None
    # NOTE: CandidateScore doesn't carry the full Transaction payload — we only
    # have the axis scores. Use them as proxy signals.

    intent_v = complaint.intent.value if isinstance(complaint.intent, IntentEnum) else str(complaint.intent)

    # --- 2. Phishing / fraud signal → treat as insufficient (no txn helps) -
    if _has_fraud_signal(complaint):
        reasons.append("complaint_contains_phishing_signal")
        # A fraud complaint is "consistent" only if a matching unauthorized
        # debit exists; otherwise we can't tie it to one transaction.
        if top.score >= min_match_confidence and top.amount_score >= 0.5:
            reasons.append("amount_matches_complaint")
            confidence = min(confidence + 0.1, 1.0)
            return EvidenceVerdictEnum.CONSISTENT, confidence, reasons
        return EvidenceVerdictEnum.INSUFFICIENT_DATA, min(confidence, 0.4), reasons

    # --- 3. Complaint lacks concrete details → insufficient --------------
    if (
        complaint.amount_bdt is None
        and not complaint.phone_numbers
        and not complaint.merchant_refs
        and intent_v == IntentEnum.UNKNOWN.value
    ):
        reasons.append("no_transactions_provided" if not match.top_candidates else "no_candidate_above_threshold")
        return EvidenceVerdictEnum.INSUFFICIENT_DATA, min(confidence, 0.4), reasons

    # --- 4. Amount check --------------------------------------------------
    amount_ok = True
    if complaint.amount_bdt is not None and top.amount_score > 0:
        # amount_score is already 0–1; require ≥ 0.5 OR high value
        if top.amount_score < (0.5 if complaint.amount_bdt < HIGH_VALUE_TAKA else 0.3):
            amount_ok = False

    if top.amount_score >= 0.7:
        reasons.append("amount_matches_complaint")
    elif top.amount_score > 0:
        reasons.append("amount_mismatch")

    # --- 5. Type compatibility ------------------------------------------
    type_ok = True
    if complaint.transaction_type is not None:
        allowed = _intent_for_txn_type(complaint.transaction_type)
        if allowed and intent_v != IntentEnum.UNKNOWN.value and intent_v not in allowed:
            type_ok = False
    if top.type_score >= 0.7:
        reasons.append("type_matches_intent")
    elif top.type_score > 0:
        reasons.append("type_mismatch")

    # --- 6. Date / status alignment --------------------------------------
    if top.date_score >= 0.7:
        reasons.append("date_within_window")
    elif top.date_score > 0:
        reasons.append("date_outside_window")
    if top.status_score >= 0.7:
        # status strong evidence: completed & consistent with intent
        pass
    if top.counterparty_score >= 0.7 and intent_v == IntentEnum.UNAUTHORIZED_TRANSACTION.value:
        reasons.append("complaint_contains_unauthorized_signal")

    # --- 7. Duplicate detection -----------------------------------------
    if intent_v == IntentEnum.DUPLICATE_DEBIT.value and top.score >= 0.8:
        reasons.append("duplicate_within_window")

    # --- 8. Decide verdict ----------------------------------------------
    if top.score < min_match_confidence:
        reasons.append("no_candidate_above_threshold")
        return EvidenceVerdictEnum.INSUFFICIENT_DATA, min(confidence, 0.4), reasons

    if amount_ok and type_ok and top.score >= min_match_confidence:
        return EvidenceVerdictEnum.CONSISTENT, confidence, reasons

    # Something contradicts the complaint.
    return EvidenceVerdictEnum.INCONSISTENT, confidence, reasons


__all__ = ["evaluate", "AMOUNT_TOLERANCE_PCT", "MIN_MATCH_CONFIDENCE"]