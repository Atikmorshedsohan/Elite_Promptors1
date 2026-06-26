"""SafetyEngine — final response gate.

Three named phases, run in order, exposed both individually and as a
single `inspect()` entry point:

    1. validate(text) -> ViolationReport
       Pure inspection. Reports every category of violation found.
       Does NOT mutate the text.

    2. rewrite(text, *, agent_summary=None) -> SafetyCheckResult
       If validation found violations, replaces the customer reply
       with the safe template. Otherwise returns the input unchanged.
       Optionally also rewrites a parallel agent summary.

    3. verify(text) -> bool
       Final guard. Returns True only if the text passes ALL category
       checks. Used as the last gate before any text leaves the system.

`inspect()` runs all three in sequence and returns a fully-typed
`SafetyVerdict` that downstream callers (ResponseService) can attach
to their output payload as an audit trail.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Iterable

from pydantic import BaseModel, ConfigDict, Field

from app.rules import safety_rules as rules
from app.utils.constants import (
    SAFE_REPLY_TEMPLATE,
    SAFE_SUMMARY_TEMPLATE,
    SAFETY_REASON_TRUNCATED,
    SAFETY_REASON_VERIFICATION_FAILED,
    SAFETY_REASON_VERIFIED,
    SAFETY_REPLY_MAX_LEN,
    SAFETY_SUMMARY_MAX_LEN,
)
from app.utils.logger import get_logger

log = get_logger(__name__)


# --- Typed results ----------------------------------------------------------


class ViolationReport(BaseModel):
    """Output of `SafetyEngine.validate`."""

    model_config = ConfigDict(extra="forbid")

    has_violation: bool
    reason_codes: list[str] = Field(default_factory=list, max_length=10)
    categories: list[str] = Field(default_factory=list, max_length=10)


class SafetyCheckResult(BaseModel):
    """Output of `SafetyEngine.rewrite`.

    Strict: customer_reply and agent_summary are both required, and the
    rewritten flag is always explicit. Compatible with the legacy
    `SafetyService.SafetyCheckResult` shape so existing callers keep
    working.
    """

    model_config = ConfigDict(extra="forbid")

    rewritten: bool
    reason_codes: list[str] = Field(default_factory=list, max_length=10)
    customer_reply: str = Field(..., min_length=1, max_length=2000)
    agent_summary: str = Field(..., min_length=1, max_length=4000)

    def to_dict(self) -> dict:
        return self.model_dump(mode="json")


class SafetyVerdict(BaseModel):
    """Final, end-to-end output of `SafetyEngine.inspect`.

    `verified=True` means the text was passed through all three phases
    and is safe to send to the customer. `verified=False` means the
    engine was unable to produce a safe text and the caller MUST treat
    the reply as blocked.
    """

    model_config = ConfigDict(extra="forbid")

    rewritten: bool
    verified: bool
    reason_codes: list[str] = Field(default_factory=list, max_length=10)
    customer_reply: str = Field(..., min_length=1, max_length=2000)
    agent_summary: str = Field(..., min_length=1, max_length=4000)
    decided_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc)
    )

    def to_dict(self) -> dict:
        return self.model_dump(mode="json")


# --- Engine -----------------------------------------------------------------


class SafetyEngine:
    """Stateless. Re-entrant. No LLM. No I/O.

    The three phases (`validate`, `rewrite`, `verify`) can be invoked
    independently — useful for tests and for diagnostics — but most
    callers should just use `inspect()`.
    """

    # ----- Phase 1: pure validation --------------------------------------

    def validate(self, text: str) -> ViolationReport:
        """Categorize every violation present in `text`.

        Pure inspection. Returns a structured report and does not
        mutate the input.
        """
        reasons = rules.classify_violations(text)
        return ViolationReport(
            has_violation=bool(reasons),
            reason_codes=reasons,
            categories=[_category_for(reason) for reason in reasons],
        )

    # ----- Phase 2: rewrite ----------------------------------------------

    def rewrite(
        self,
        customer_reply: str,
        *,
        agent_summary: str | None = None,
    ) -> SafetyCheckResult:
        """If `customer_reply` has any violation, replace with the safe
        template. Truncate aggressively long text defensively.
        """
        report = self.validate(customer_reply)
        reasons: list[str] = list(report.reason_codes)
        rewritten = report.has_violation

        if rewritten:
            log.warning(
                "safety_rewrite_applied",
                extra={
                    "stage": "safety.rewrite",
                    "reasons": reasons,
                    "categories": report.categories,
                },
            )

        safe_reply = (
            SAFE_REPLY_TEMPLATE if rewritten else customer_reply
        )
        safe_summary = agent_summary or SAFE_SUMMARY_TEMPLATE

        if len(safe_reply) > SAFETY_REPLY_MAX_LEN:
            safe_reply = safe_reply[:SAFETY_REPLY_MAX_LEN]
            reasons.append(SAFETY_REASON_TRUNCATED)
            rewritten = True
        if len(safe_summary) > SAFETY_SUMMARY_MAX_LEN:
            safe_summary = safe_summary[:SAFETY_SUMMARY_MAX_LEN]
            reasons.append(SAFETY_REASON_TRUNCATED)
            rewritten = True

        # Deduplicate reason codes preserving order
        deduped = _dedupe_preserve_order(reasons)

        return SafetyCheckResult(
            rewritten=rewritten,
            reason_codes=deduped,
            customer_reply=safe_reply,
            agent_summary=safe_summary,
        )

    # ----- Phase 3: verification -----------------------------------------

    def verify(self, text: str) -> tuple[bool, list[str]]:
        """Final guard. Returns (passed, reasons).

        `passed=True` means the text is safe to send. `passed=False`
        returns the reason codes that triggered the failure.

        This is essentially `validate` exposed as a boolean. It exists
        as its own method so the *intent* — "I'm about to send this" —
        is explicit at the call site.
        """
        report = self.validate(text)
        if report.has_violation:
            return False, [SAFETY_REASON_VERIFICATION_FAILED, *report.reason_codes]
        return True, [SAFETY_REASON_VERIFIED]

    # ----- Unified entry point -------------------------------------------

    def inspect(
        self,
        customer_reply: str,
        *,
        agent_summary: str | None = None,
    ) -> SafetyVerdict:
        """Run validate → rewrite → verify in order.

        Returns a fully-typed `SafetyVerdict` ready to attach to the
        outgoing response payload.
        """
        # Phase 2: rewrite (this also runs phase 1 internally)
        rewritten_result = self.rewrite(
            customer_reply, agent_summary=agent_summary
        )

        # Phase 3: verify the *rewritten* text (defence-in-depth — if a
        # rewrite slipped through a violation we catch it here).
        passed, verify_reasons = self.verify(rewritten_result.customer_reply)

        all_reasons = _dedupe_preserve_order([
            *rewritten_result.reason_codes,
            *verify_reasons,
        ])

        if not passed:
            log.error(
                "safety_verification_failed",
                extra={
                    "stage": "safety.verify",
                    "reasons": all_reasons,
                },
            )
            # Last-resort fallback: use the safe template.
            return SafetyVerdict(
                rewritten=True,
                verified=False,
                reason_codes=all_reasons,
                customer_reply=SAFE_REPLY_TEMPLATE,
                agent_summary=rewritten_result.agent_summary or SAFE_SUMMARY_TEMPLATE,
            )

        if rewritten_result.rewritten:
            log.info(
                "safety_rewritten_then_verified",
                extra={"reasons": all_reasons},
            )
        else:
            log.debug(
                "safety_passed_clean",
                extra={"reasons": all_reasons},
            )

        return SafetyVerdict(
            rewritten=rewritten_result.rewritten,
            verified=True,
            reason_codes=all_reasons,
            customer_reply=rewritten_result.customer_reply,
            agent_summary=rewritten_result.agent_summary,
        )


# --- Helpers ----------------------------------------------------------------


# Map a stable reason code -> a friendly category name for the report.
_REASON_TO_CATEGORY: dict[str, str] = {
    "safety_request_secret_echo_blocked": "secret_request",
    "safety_request_card_echo_blocked": "card_request",
    "safety_promise_refund_blocked": "refund_promise",
    "safety_promise_recovery_blocked": "recovery_promise",
    "safety_promise_unblock_blocked": "unblock_promise",
    "safety_unofficial_channel_blocked": "unofficial_channel",
    "safety_truncated": "length_cap",
}


def _category_for(reason_code: str) -> str:
    return _REASON_TO_CATEGORY.get(reason_code, "other")


def _dedupe_preserve_order(items: Iterable[str]) -> list[str]:
    """Deduplicate while preserving first-seen order."""
    seen: set[str] = set()
    out: list[str] = []
    for item in items:
        if item not in seen:
            seen.add(item)
            out.append(item)
    return out


__all__ = [
    "SafetyEngine",
    "SafetyCheckResult",
    "SafetyVerdict",
    "ViolationReport",
]