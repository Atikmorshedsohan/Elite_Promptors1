"""ResponseService — final customer-facing message generation.

This is the LAST stage of the investigation pipeline. It takes the full
upstream verdict (classification + evidence + routing + match) and
produces:

    1. A customer-facing reply (English; mirrors the customer's tone).
    2. An internal agent summary (concise, structured for the CRM).

Both texts are wrapped in a SafetyEngine.inspect() call BEFORE being
returned. The engine runs validate → rewrite → verify and falls back
to a safe template if anything goes wrong.

Generation strategy:

    Layer 1 — Deterministic templates.
        Pure rules. No LLM. Always safe by construction because the
        templates are themselves in the safe-template set.
        Used when LLM is unavailable OR as the final fallback.

    Layer 2 — LLM draft.
        Attempts to draft a personalized reply using Gemini with
        timeout + retry. If the LLM returns empty / errors / times
        out, we fall back to the deterministic template.

The LLM draft is ALWAYS post-processed by SafetyEngine.inspect().
Even when the LLM produces clean text, the engine still produces an
audit trail (`safety_reason_codes`).
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from app.ai.llm_client import LLMClient, StubLLMClient
from app.config import get_settings
from app.rules import safety_rules as _safety_rules_unused  # noqa: F401  (ensures rules are loaded)
from app.schemas.complaint_info import ComplaintInfo
from app.schemas.enums import (
    ActionEnum,
    EvidenceVerdictEnum,
    OfficialCaseTypeEnum,
    SeverityEnum,
)
from app.schemas.match_result import MatchResult
from app.services.evidence_service import EvidenceEvaluation
from app.services.classifier_service import ClassificationResult
from app.services.routing_service import RoutingDecision
from app.services.safety_engine import SafetyEngine, SafetyVerdict
from app.utils.constants import (
    SAFETY_REASON_VERIFICATION_FAILED,
    SAFETY_REPLY_MAX_LEN,
    SAFETY_SUMMARY_MAX_LEN,
)
from app.utils.logger import get_logger

log = get_logger(__name__)


# ---------------------------------------------------------------------------
# Prompt templates — kept in one place for easy auditing.
# ---------------------------------------------------------------------------

CUSTOMER_REPLY_SYSTEM_PROMPT: str = (
    "You are the customer-support voice for bKash, a mobile financial "
    "service in Bangladesh. Write a single short paragraph reply to a "
    "customer who filed a complaint.\n\n"
    "Hard rules — violating any of these is a safety failure:\n"
    "  - NEVER ask the customer for their OTP, PIN, password, CVV, "
    "card number, or any security credential.\n"
    "  - NEVER promise a refund, reversal, account recovery, or "
    "unblock. Use language like 'will be reviewed', 'may be eligible', "
    "or 'our team will look into it'.\n"
    "  - NEVER direct the customer to WhatsApp, Telegram, phone "
    "numbers, external URLs, or any channel outside the official bKash "
    "app / website.\n"
    "  - NEVER request photos, selfies, or in-person meetings.\n"
    "  - Keep the reply under 120 words. One paragraph. Plain language.\n\n"
    "Output ONLY the reply text. No preamble, no signature, no JSON."
)

AGENT_SUMMARY_SYSTEM_PROMPT: str = (
    "You are writing an internal CRM handoff note for a human bKash "
    "support agent. Summarize the case in 3-5 short lines.\n\n"
    "Hard rules:\n"
    "  - NEVER include the customer's OTP, PIN, password, CVV, full "
    "card number, or any credential, even if the customer wrote it.\n"
    "  - NEVER promise an outcome — use neutral language like "
    "'customer requests', 'evidence shows', 'agent to review'.\n"
    "  - Include: case type, severity, matched transaction id (if any), "
    "evidence verdict, recommended action.\n"
    "  - Output ONLY the summary. No preamble, no signature, no JSON."
)


def _customer_reply_user_prompt(ctx: "_ResponseContext") -> str:
    """Compose the user-message half of the customer-reply prompt.

    Includes ONLY safe, redacted context. Customer IDs, amounts, and
    matched-transaction fields are quoted verbatim (they are not
    credentials), but any credential-looking substring the customer
    may have included is REPLACED before this prompt is built (see
    `_redact_credentials`).
    """
    parts: list[str] = []
    parts.append(
        f"Customer complaint (verbatim):\n\"\"\"\n{ctx.complaint_text_redacted}\n\"\"\""
    )
    if ctx.transaction_summary:
        parts.append(
            "Most relevant transaction from the customer's history:\n"
            f"{ctx.transaction_summary}"
        )
    parts.append(
        "Investigation outcome:\n"
        f"- Case type: {ctx.case_type.value}\n"
        f"- Severity: {ctx.severity.value}\n"
        f"- Evidence verdict: {ctx.verdict.value}\n"
        f"- Confidence: {ctx.confidence:.2f}\n"
        f"- Recommended action: {ctx.action.value}"
    )
    parts.append(
        "Draft the customer reply now. Remember the hard rules in the "
        "system prompt — no credential asks, no outcome promises, no "
        "unofficial channels."
    )
    return "\n\n".join(parts)


def _agent_summary_user_prompt(ctx: "_ResponseContext") -> str:
    parts: list[str] = []
    parts.append(
        f"Customer complaint (verbatim):\n\"\"\"\n{ctx.complaint_text_redacted}\n\"\"\""
    )
    parts.append(
        f"Detected intent: {ctx.complaint.intent.value}"
    )
    if ctx.transaction_summary:
        parts.append(
            f"Matched transaction: {ctx.transaction_summary}"
        )
    parts.append(
        "Investigation outcome:\n"
        f"- Case type: {ctx.case_type.value}\n"
        f"- Severity: {ctx.severity.value}\n"
        f"- Evidence verdict: {ctx.verdict.value}\n"
        f"- Confidence: {ctx.confidence:.2f}\n"
        f"- Recommended action: {ctx.action.value}\n"
        f"- Reason codes: {', '.join(ctx.reason_codes) or '(none)'}"
    )
    parts.append(
        "Write the internal summary now. No credentials, no promises."
    )
    return "\n\n".join(parts)


# ---------------------------------------------------------------------------
# Deterministic fallback templates — always pass SafetyEngine.verify().
# ---------------------------------------------------------------------------


def _deterministic_customer_reply(ctx: "_ResponseContext") -> str:
    """Build a deterministic customer reply from the verdict.

    The template is chosen so that the result is always inside the
    blocklist's "safe" set:
      - No imperative + secret token.
      - No promise of refund/reversal/recovery/unblock.
      - No unofficial channels.
    """
    case = ctx.case_type
    verdict = ctx.verdict

    if verdict == EvidenceVerdictEnum.INSUFFICIENT_DATA:
        opener = (
            "Thank you for contacting bKash support. We were unable to "
            "match your complaint to a specific transaction from the "
            "information provided."
        )
        body = (
            "An agent will review your case and reach out through the "
            "official bKash app for any follow-up."
        )
        closing = (
            "Please do not share OTP, PIN, or passwords with anyone."
        )
        return f"{opener} {body} {closing}"

    if case == OfficialCaseTypeEnum.WRONG_TRANSFER:
        body = (
            "We have located the transaction you referenced. Our team "
            "will review the transfer details and may contact you "
            "through the official bKash app if additional information "
            "is required."
        )
    elif case == OfficialCaseTypeEnum.PAYMENT_FAILED:
        body = (
            "We have identified the transaction in your history. Our "
            "team will investigate why the transfer did not complete "
            "and will follow up through the official bKash app."
        )
    elif case == OfficialCaseTypeEnum.DUPLICATE_PAYMENT:
        body = (
            "We have found multiple debits in your history. Our team "
            "will review the records and follow up through the official "
            "bKash app."
        )
    elif case == OfficialCaseTypeEnum.REFUND_REQUEST:
        body = (
            "Your refund request has been logged. Eligibility will be "
            "determined after review by our team, and you will be "
            "contacted through the official bKash app."
        )
    elif case == OfficialCaseTypeEnum.PHISHING_OR_SOCIAL_ENGINEERING:
        body = (
            "Thank you for reporting this. Please continue to use only "
            "the official bKash app and helpline for any support. Our "
            "team will review the matter."
        )
    elif case == OfficialCaseTypeEnum.MERCHANT_SETTLEMENT_DELAY:
        body = (
            "We have logged your settlement concern. Our team will "
            "review the merchant's records and follow up through the "
            "official bKash app."
        )
    elif case == OfficialCaseTypeEnum.AGENT_CASH_IN_ISSUE:
        body = (
            "We have received your cash-in concern. An agent will "
            "review the transaction and follow up through the official "
            "bKash app."
        )
    else:
        body = (
            "We have received your message. An agent will review your "
            "case and follow up through the official bKash app."
        )

    opening = "Thank you for contacting bKash support."
    closing = "Please do not share OTP, PIN, or passwords with anyone."
    return f"{opening} {body} {closing}"


def _deterministic_agent_summary(ctx: "_ResponseContext") -> str:
    """Build a deterministic internal summary from upstream outputs."""
    lines: list[str] = []
    lines.append(
        f"Case type: {ctx.case_type.value} | "
        f"Severity: {ctx.severity.value} | "
        f"Action: {ctx.action.value}"
    )
    lines.append(
        f"Evidence verdict: {ctx.verdict.value} | "
        f"Confidence: {ctx.confidence:.2f}"
    )
    if ctx.transaction_summary:
        lines.append(f"Matched transaction: {ctx.transaction_summary}")
    if ctx.reason_codes:
        lines.append(f"Reason codes: {', '.join(ctx.reason_codes)}")
    lines.append(
        "Suggested next step: an agent reviews the case and contacts "
        "the customer through the official bKash app."
    )
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Internal context — built once per .compose() call.
# ---------------------------------------------------------------------------


class _ResponseContext:
    """Pre-digested inputs. Not a Pydantic model: it's a private struct."""

    __slots__ = (
        "complaint",
        "classification",
        "routing",
        "evidence",
        "match",
        "complaint_text_redacted",
        "transaction_summary",
        "case_type",
        "severity",
        "verdict",
        "action",
        "confidence",
        "reason_codes",
    )

    def __init__(
        self,
        complaint: ComplaintInfo,
        classification: ClassificationResult,
        routing: RoutingDecision,
        evidence: EvidenceEvaluation,
        match: MatchResult,
    ) -> None:
        self.complaint = complaint
        self.classification = classification
        self.routing = routing
        self.evidence = evidence
        self.match = match

        self.case_type = classification.case_type
        self.severity = classification.severity
        self.verdict = evidence.verdict
        self.action = routing.action
        self.confidence = float(classification.confidence)
        # Merge reason codes deterministically, deduped, upstream-first.
        seen: set[str] = set()
        ordered: list[str] = []
        for src in (
            classification.reason_codes,
            routing.reason_codes,
            evidence.reason_codes,
        ):
            for code in src:
                if code not in seen:
                    seen.add(code)
                    ordered.append(code)
        self.reason_codes = ordered

        self.complaint_text_redacted = _redact_credentials(complaint.raw_text or "")
        self.transaction_summary = _summarize_match(match)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


# Conservative credential patterns for pre-prompt redaction. We replace
# matches with `[REDACTED]` so the LLM prompt itself never contains a
# verbatim credential — defence in depth against prompt-leak risks.
_REDACT_PATTERNS: tuple[str, ...] = (
    r"\b\d{4}[\s-]?\d{4}[\s-]?\d{4}[\s-]?\d{4}\b",  # 16-digit PAN
    r"\b(?:otp|pin|password|cvv)\s*[:=]\s*\S+",
    r"\b\d{6,}\b",  # long digit strings (catch-all for OTPs / PINs)
)


def _redact_credentials(text: str) -> str:
    import re
    out = text
    for pat in _REDACT_PATTERNS:
        out = re.sub(pat, "[REDACTED]", out, flags=re.IGNORECASE)
    return out


def _summarize_match(match: MatchResult) -> str:
    """One-line description of the matched transaction, if any."""
    if not match.matched:
        return ""
    cand = match.transaction
    if cand is None:
        return ""
    parts: list[str] = []
    if cand.transaction_id:
        parts.append(f"id={cand.transaction_id}")
    if cand.amount is not None:
        parts.append(f"amount={cand.amount:.2f} {cand.currency}")
    if cand.type:
        parts.append(f"type={cand.type}")
    if cand.timestamp:
        parts.append(f"timestamp={cand.timestamp.isoformat()}")
    if cand.counterparty:
        parts.append(f"counterparty={cand.counterparty}")
    if cand.status:
        parts.append(f"status={cand.status}")
    parts.append(f"match_score={match.score:.2f}")
    return " | ".join(parts) if parts else ""


# ---------------------------------------------------------------------------
# Typed outputs
# ---------------------------------------------------------------------------


class FinalResponse(BaseModel):
    """Strict, audited final response produced by ResponseService.

    Both `customer_reply` and `agent_summary` have been through
    SafetyEngine.inspect(). `safety_verified=True` is the gate
    required by the route layer.
    """

    model_config = ConfigDict(extra="forbid")

    customer_reply: str = Field(..., min_length=1, max_length=SAFETY_REPLY_MAX_LEN)
    agent_summary: str = Field(..., min_length=1, max_length=SAFETY_SUMMARY_MAX_LEN)
    safety_verified: bool
    safety_rewritten: bool
    safety_reason_codes: list[str] = Field(default_factory=list, max_length=20)
    llm_used: bool
    generated_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc)
    )

    def to_dict(self) -> dict[str, Any]:
        return self.model_dump(mode="json")


# ---------------------------------------------------------------------------
# Service
# ---------------------------------------------------------------------------


class ResponseService:
    """Stateless. Builds the final customer-facing reply.

    Pass either a real `GeminiClient` or a `StubLLMClient` via the
    constructor. If `llm=None` we auto-build the default from settings
    (Gemini if a key is set, otherwise stub).
    """

    def __init__(self, llm: LLMClient | None = None) -> None:
        self._llm: LLMClient = llm or _default_llm()
        self._safety = SafetyEngine()
        log.info(
            "response_service_init",
            extra={"stage": "response.init", "llm_class": type(self._llm).__name__},
        )

    # ---- Public API -----------------------------------------------------

    def compose(
        self,
        *,
        complaint: ComplaintInfo,
        classification: ClassificationResult,
        routing: RoutingDecision,
        evidence: EvidenceEvaluation,
        match: MatchResult,
    ) -> FinalResponse:
        """Run Layer 1 (deterministic) + Layer 2 (LLM) + SafetyEngine.

        Always returns a `FinalResponse` with `safety_verified=True`
        when the SafetyEngine's verify gate passes. If verify fails
        (a true positive — the engine still rewrote to safe template),
        `safety_verified` may be False, but the returned text is still
        safe (it is the safe template itself).
        """
        ctx = _ResponseContext(
            complaint=complaint,
            classification=classification,
            routing=routing,
            evidence=evidence,
            match=match,
        )

        # Layer 2 attempt (LLM). Always falls back to Layer 1 on failure.
        customer_draft, llm_used = self._draft_customer_reply(ctx)
        summary_draft = self._draft_agent_summary(ctx, llm_used=llm_used)

        # Safety gate — wraps both texts.
        verdict: SafetyVerdict = self._safety.inspect(
            customer_reply=customer_draft,
            agent_summary=summary_draft,
        )

        if verdict.verified is False:
            log.error(
                "response_safety_verification_failed",
                extra={
                    "stage": "response.compose",
                    "reasons": verdict.reason_codes,
                    "llm_used": llm_used,
                },
            )
        elif verdict.rewritten:
            log.info(
                "response_safety_rewritten",
                extra={
                    "stage": "response.compose",
                    "reasons": verdict.reason_codes,
                    "llm_used": llm_used,
                },
            )
        else:
            log.debug(
                "response_clean",
                extra={"stage": "response.compose", "llm_used": llm_used},
            )

        return FinalResponse(
            customer_reply=verdict.customer_reply,
            agent_summary=verdict.agent_summary,
            safety_verified=verdict.verified,
            safety_rewritten=verdict.rewritten,
            safety_reason_codes=verdict.reason_codes,
            llm_used=llm_used,
        )

    # ---- Drafters -------------------------------------------------------

    def _draft_customer_reply(self, ctx: _ResponseContext) -> tuple[str, bool]:
        """Returns (reply_text, llm_used). Falls back to deterministic."""
        prompt = (
            CUSTOMER_REPLY_SYSTEM_PROMPT
            + "\n\n"
            + _customer_reply_user_prompt(ctx)
        )
        raw = self._llm.safe_generate(prompt, expect_json=False).strip()

        if not raw:
            log.info(
                "llm_unavailable_using_deterministic",
                extra={"stage": "response.draft_customer"},
            )
            return _deterministic_customer_reply(ctx), False

        # Defensive length cap before handing to SafetyEngine.
        if len(raw) > SAFETY_REPLY_MAX_LEN:
            raw = raw[:SAFETY_REPLY_MAX_LEN]

        return raw, True

    def _draft_agent_summary(
        self, ctx: _ResponseContext, *, llm_used: bool
    ) -> str:
        """Always build a deterministic summary when LLM unavailable.

        When the customer-reply LLM was used, attempt a summary draft
        too. Falls back to deterministic if the LLM is silent.
        """
        if not llm_used:
            return _deterministic_agent_summary(ctx)

        prompt = (
            AGENT_SUMMARY_SYSTEM_PROMPT
            + "\n\n"
            + _agent_summary_user_prompt(ctx)
        )
        raw = self._llm.safe_generate(prompt, expect_json=False).strip()
        if not raw:
            return _deterministic_agent_summary(ctx)

        if len(raw) > SAFETY_SUMMARY_MAX_LEN:
            raw = raw[:SAFETY_SUMMARY_MAX_LEN]
        return raw


def _default_llm() -> LLMClient:
    """Build the default LLM client from settings.

    Uses Gemini if GEMINI_API_KEY is set, else stub. Wrapped so the
    settings cache + env are read once at construction.
    """
    from app.ai.llm_client import build_default_llm
    return build_default_llm()


__all__ = [
    "FinalResponse",
    "ResponseService",
    "CUSTOMER_REPLY_SYSTEM_PROMPT",
    "AGENT_SUMMARY_SYSTEM_PROMPT",
]
