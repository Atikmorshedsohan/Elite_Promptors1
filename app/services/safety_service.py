"""SafetyService — guard the output before it leaves the system.

Three responsibilities:
    1. Audit text for unsafe promise patterns (refund/guarantee/reset)
    2. Audit text for unsafe request patterns (asking for OTP/PIN/CVV)
    3. Rewrite offending text to a safe template and append a reason code

Pure service — no LLM, no I/O. All decision logic lives in
`app/utils/constants.py` (blocklist regex) and `app/utils/helpers.py`
(`contains_any`).
"""
from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from ..utils.constants import (
    SAFE_REPLY_TEMPLATE,
    SAFE_SUMMARY_TEMPLATE,
    UNSAFE_PROMISE_PATTERNS,
    UNSAFE_REQUEST_PATTERNS,
)
from ..utils.helpers import contains_any
from ..utils.logger import get_logger

log = get_logger(__name__)


class SafetyCheckResult(BaseModel):
    """Strict output of SafetyService."""

    model_config = ConfigDict(extra="forbid")

    rewritten: bool
    reason_codes: list[str] = Field(default_factory=list, max_length=10)
    customer_reply: str = Field(..., min_length=1, max_length=1000)
    agent_summary: str = Field(..., min_length=1, max_length=2000)

    def to_dict(self) -> dict:
        return self.model_dump(mode="json")


class SafetyService:
    """Stateless. Re-entrant. No LLM."""

    def sanitize_reply(
        self,
        customer_reply: str,
        *,
        agent_summary: str | None = None,
    ) -> SafetyCheckResult:
        reasons: list[str] = []
        rewritten = False
        safe_reply = customer_reply
        safe_summary = agent_summary or SAFE_SUMMARY_TEMPLATE

        # 1. Never echo back a request for OTP/PIN/CVV — replace immediately.
        if contains_any(customer_reply, UNSAFE_REQUEST_PATTERNS):
            reasons.append("safety_request_echo_blocked")
            safe_reply = SAFE_REPLY_TEMPLATE
            rewritten = True

        # 2. Never make a promise we cannot back (refund / unblock / guarantee).
        if contains_any(safe_reply, UNSAFE_PROMISE_PATTERNS):
            reasons.append("safety_violation_rewritten")
            safe_reply = SAFE_REPLY_TEMPLATE
            rewritten = True

        # 3. Cap length defensively (defence-in-depth even though the schema
        #    already enforces it). The schema will reject longer output, but
        #    we truncate here to keep the rewritten text clean.
        if len(safe_reply) > 1000:
            safe_reply = safe_reply[:1000]
            reasons.append("safety_truncated")

        if len(safe_summary) > 2000:
            safe_summary = safe_summary[:2000]
            reasons.append("safety_truncated")

        if rewritten:
            log.warning(
                "safety_rewrite_applied",
                extra={
                    "stage": "safety",
                    "reasons": reasons,
                },
            )

        return SafetyCheckResult(
            rewritten=rewritten,
            reason_codes=reasons,
            customer_reply=safe_reply,
            agent_summary=safe_summary,
        )


__all__ = ["SafetyService", "SafetyCheckResult"]  # explicit export