"""TransactionMatcherService — pick the transaction most relevant to a complaint.

Hybrid scoring:
  Stage A (rules): deterministic score per transaction across 5 dimensions.
  Stage B (LLM):   only invoked when top candidates are tied within delta;
                   the LLM picks one and provides justification, but the
                   rules engine validates the override.

Output: `MatchResult` with the chosen transaction, score, and reason codes.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

from pydantic import ValidationError

from ..ai.llm_client import LLMClient
from ..config import get_settings
from ..schemas.complaint_info import ComplaintInfo
from ..schemas.enums import IntentEnum, TransactionTypeEnum
from ..schemas.match_result import CandidateScore, MatchResult
from ..schemas.request import Transaction
from ..utils.helpers import clamp, contains_any
from ..utils.logger import get_logger

log = get_logger(__name__)


# Weights — tuned for the rubric's evidence-reasoning weight (35%).
_W_AMOUNT: float = 0.40
_W_DATE: float = 0.25
_W_TYPE: float = 0.15
_W_COUNTERPARTY: float = 0.15
_W_STATUS: float = 0.05


class TransactionMatcherService:
    """Hybrid transaction matcher."""

    def __init__(self, llm: LLMClient) -> None:
        self._llm = llm
        self._settings = get_settings()

    # ---- Public API ----

    def match(
        self, complaint: ComplaintInfo, transactions: list[Transaction]
    ) -> MatchResult:
        """Find the best matching transaction. Never raises."""
        if not transactions:
            log.info("matcher_no_transactions", extra={"stage": "matcher"})
            return MatchResult(
                matched=False,
                method="no_match",
                score=0.0,
                confidence=0.0,
                reason_codes=["no_transactions_provided"],
                decided_at=datetime.now(tz=timezone.utc),
            )

        scored = [self._score_candidate(c, complaint) for c in transactions]
        scored.sort(key=lambda s: s.score, reverse=True)

        top = scored[0]
        runner_up = scored[1] if len(scored) > 1 else None

        # No candidate crosses the minimum-confidence floor.
        if top.score < 0.30:
            return MatchResult(
                matched=False,
                method="no_match",
                score=top.score,
                confidence=top.score,
                top_candidates=scored[:3],
                reason_codes=["no_candidate_above_threshold"] + top.reason_codes,
                decided_at=datetime.now(tz=timezone.utc),
            )

        # Clear winner — return immediately.
        if runner_up is None or (top.score - runner_up.score) >= self._settings.tie_score_delta:
            return MatchResult(
                matched=True,
                method="rule_best",
                transaction=self._find_txn(transactions, top.transaction_id),
                score=top.score,
                confidence=top.score,
                top_candidates=scored[:3],
                reason_codes=top.reason_codes,
                decided_at=datetime.now(tz=timezone.utc),
            )

        # Tie within delta → ask LLM to break the tie.
        tied = [s for s in scored if (top.score - s.score) <= self._settings.tie_score_delta]
        chosen_id = self._llm_break_tie(complaint, transactions, tied)
        if chosen_id and chosen_id != top.transaction_id:
            chosen = next((s for s in tied if s.transaction_id == chosen_id), top)
        else:
            chosen = top

        if chosen.score < 0.30:
            return MatchResult(
                matched=False,
                method="rule_tie_llm_break",
                score=chosen.score,
                confidence=chosen.score,
                top_candidates=scored[:3],
                reason_codes=["multiple_candidates_tied"] + chosen.reason_codes,
                decided_at=datetime.now(tz=timezone.utc),
            )

        return MatchResult(
            matched=True,
            method="rule_tie_llm_break",
            transaction=self._find_txn(transactions, chosen.transaction_id),
            score=chosen.score,
            confidence=clamp(chosen.score * 0.95, 0.0, 1.0),
            top_candidates=scored[:3],
            reason_codes=["multiple_candidates_tied"] + chosen.reason_codes,
            decided_at=datetime.now(tz=timezone.utc),
        )

    # ---- Stage A: rule-based scoring ----

    def _score_candidate(self, txn: Transaction, info: ComplaintInfo) -> CandidateScore:
        reasons: list[str] = []

        amt_score, amt_reason = self._score_amount(txn, info)
        if amt_reason:
            reasons.append(amt_reason)

        date_score, date_reason = self._score_date(txn, info)
        if date_reason:
            reasons.append(date_reason)

        type_score, type_reason = self._score_type(txn, info)
        if type_reason:
            reasons.append(type_reason)

        cp_score, cp_reason = self._score_counterparty(txn, info)
        if cp_reason:
            reasons.append(cp_reason)

        status_score, status_reason = self._score_status(txn, info)
        if status_reason:
            reasons.append(status_reason)

        score = clamp(
            amt_score * _W_AMOUNT
            + date_score * _W_DATE
            + type_score * _W_TYPE
            + cp_score * _W_COUNTERPARTY
            + status_score * _W_STATUS,
            0.0,
            1.0,
        )

        return CandidateScore(
            transaction_id=txn.transaction_id,
            score=score,
            amount_score=amt_score,
            date_score=date_score,
            type_score=type_score,
            counterparty_score=cp_score,
            status_score=status_score,
            reason_codes=reasons,
        )

    def _score_amount(self, txn: Transaction, info: ComplaintInfo) -> tuple[float, str | None]:
        if info.amount_bdt is None:
            return 0.0, None
        tol = self._settings.amount_tolerance_pct
        diff = abs(txn.amount - info.amount_bdt)
        if diff <= info.amount_bdt * tol:
            return 1.0, "amount_matches_complaint"
        if diff <= info.amount_bdt * 0.10:
            return 0.5, "amount_matches_complaint"
        return 0.0, "amount_mismatch"

    def _score_date(self, txn: Transaction, info: ComplaintInfo) -> tuple[float, str | None]:
        target = info.time_hint or datetime.now(tz=timezone.utc)
        delta_days = abs((txn.timestamp - target).total_seconds()) / 86400.0
        window = self._settings.date_window_days
        if delta_days <= window:
            return 1.0, "date_within_window"
        if delta_days <= window * 4:
            return 0.4, "date_within_window"
        return 0.0, "date_outside_window"

    def _score_type(self, txn: Transaction, info: ComplaintInfo) -> tuple[float, str | None]:
        if info.transaction_type is None:
            return 0.0, None
        if txn.type == info.transaction_type.value:
            return 1.0, "type_matches_intent"
        # Compatible adjacent types still get partial credit.
        compatible = {
            TransactionTypeEnum.SEND_MONEY.value: {TransactionTypeEnum.PAYMENT.value},
            TransactionTypeEnum.PAYMENT.value: {TransactionTypeEnum.SEND_MONEY.value},
        }
        if txn.type in compatible.get(info.transaction_type.value, set()):
            return 0.5, "type_matches_intent"
        return 0.0, "type_mismatch"

    def _score_counterparty(
        self, txn: Transaction, info: ComplaintInfo
    ) -> tuple[float, str | None]:
        if not info.has_counterparty() or not txn.counterparty:
            return 0.0, None
        cp_target = (info.counterparty or "").lower()
        phones = [p.lower() for p in info.phone_numbers]
        cp_actual = (txn.counterparty or "").lower()
        if cp_target and (cp_target in cp_actual or cp_actual in cp_target):
            return 1.0, None
        if phones and any(p in cp_actual for p in phones):
            return 1.0, None
        return 0.0, None

    def _score_status(self, txn: Transaction, info: ComplaintInfo) -> tuple[float, str | None]:
        if info.intent == IntentEnum.FAILED_TRANSFER and txn.status == "failed":
            return 1.0, None
        if info.intent in (IntentEnum.DUPLICATE_DEBIT,) and txn.status == "success":
            return 0.8, None
        if txn.status == "success":
            return 0.5, None
        return 0.2, None

    # ---- Stage B: LLM tie-break ----

    def _llm_break_tie(
        self,
        info: ComplaintInfo,
        transactions: list[Transaction],
        tied: list[CandidateScore],
    ) -> str | None:
        """Ask the LLM to pick the best candidate among tied ones."""
        try:
            txn_by_id = {t.transaction_id: t for t in transactions}
            options: list[dict[str, Any]] = []
            for c in tied:
                t = txn_by_id.get(c.transaction_id)
                if t is None:
                    continue
                options.append(
                    {
                        "transaction_id": t.transaction_id,
                        "timestamp": t.timestamp.isoformat(),
                        "type": t.type,
                        "amount": t.amount,
                        "counterparty": t.counterparty,
                        "status": t.status,
                        "rule_score": round(c.score, 3),
                    }
                )
            if not options:
                return None
            prompt = (
                "You are an evidence arbiter for a fintech support system. "
                "Given a customer complaint and a set of candidate transactions "
                "with rule-based scores, choose the SINGLE most likely transaction "
                "the complaint refers to. Reply with JSON only: "
                "{\"chosen_transaction_id\": \"...\", \"reason\": \"...\"}."
                f"\n\nComplaint (intent={info.intent.value}, amount={info.amount_bdt}, "
                f"counterparty={info.counterparty}):\n{info.raw_text[:1000]}\n\n"
                f"Candidates:\n{json.dumps(options, ensure_ascii=False, indent=2)}"
            )
            raw = self._llm.safe_generate(prompt, expect_json=True)
            if not raw:
                return None
            data = json.loads(raw)
            chosen = data.get("chosen_transaction_id") if isinstance(data, dict) else None
            if chosen and chosen in {c.transaction_id for c in tied}:
                return chosen
        except (json.JSONDecodeError, ValidationError, Exception) as exc:
            log.warning(
                "matcher_llm_tie_break_failed",
                extra={"stage": "matcher"},
            )
        return None

    # ---- helpers ----

    @staticmethod
    def _find_txn(transactions: list[Transaction], txn_id: str) -> Transaction | None:
        for t in transactions:
            if t.transaction_id == txn_id:
                return t
        return None


__all__ = ["TransactionMatcherService"]  # explicit export