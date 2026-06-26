"""InvestigationService — orchestrates the 12-stage analysis pipeline.

Stages:
  1.  Parse + validate the inbound `AnalyzeTicketRequest`.
  2.  ComplaintAnalyzerService  -> ComplaintInfo
  3.  TransactionMatcherService -> MatchResult
  4.  EvidenceEngine.evaluate   -> EvidenceEvaluation
  5.  ClassificationEngine      -> ClassificationResult
  6.  RoutingService            -> RoutingDecision
  7.  ResponseService           -> FinalResponse (LLM draft + SafetyEngine)
  8.  ReviewService             -> ReviewTicket (when human review needed)
  9.  Build the `AnalyzeTicketResponse` envelope (strict Pydantic).
 10.  Cross-field validation runs inside the response model.
 11.  Final safety check at the route layer re-validates.
 12.  Emit logs + return.

This service is the SINGLE entry point used by the route handler. It
holds no state and is re-entrant.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from app.ai.llm_client import LLMClient
from app.schemas.complaint_info import ComplaintInfo
from app.schemas.enums import (
    ActionEnum,
    CaseTypeEnum,
    DepartmentEnum,
    EvidenceVerdictEnum,
    OfficialCaseTypeEnum,
    SeverityEnum,
)
from app.schemas.match_result import MatchResult
from app.schemas.request import AnalyzeTicketRequest
from app.schemas.response import AnalyzeTicketResponse
from app.services.classifier_service import ClassificationEngine, ClassificationResult
from app.services.complaint_service import ComplaintAnalyzerService
from app.services.evidence_service import EvidenceEngine, EvidenceEvaluation
from app.services.matcher_service import TransactionMatcherService
from app.services.response_service import FinalResponse, ResponseService
from app.services.review_service import ReviewService, ReviewTicket
from app.services.routing_service import RoutingDecision, RoutingService
from app.utils.logger import get_logger

log = get_logger(__name__)


class InvestigationPipeline:
    """Composes all 8 services into a single call.

    Construct once with the LLM client, then call `.run(req)`.
    """

    def __init__(self, llm: LLMClient) -> None:
        self.complaint_service = ComplaintAnalyzerService(llm=llm)
        self.matcher_service = TransactionMatcherService(llm=llm)
        self.evidence_engine = EvidenceEngine()
        self.classifier = ClassificationEngine()
        self.routing = RoutingService()
        self.response = ResponseService(llm=llm)
        self.review = ReviewService()

    # ---- Public API -----------------------------------------------------

    def run(self, req: AnalyzeTicketRequest) -> AnalyzeTicketResponse:
        """Execute the pipeline. Returns the strict response envelope."""
        log.info(
            "investigation_start",
            extra={
                "ticket_id": req.ticket_id,
                "tx_count": len(req.transactions),
                "stage": "pipeline.start",
            },
        )

        # Stage 2 — extract structured complaint signals
        complaint_info = self.complaint_service.analyze(req.complaint)

        # Stage 3 — match to a transaction in the customer's history
        match_result = self.matcher_service.match(
            complaint=complaint_info,
            transactions=req.transactions,
        )

        # Stage 4 — evidence evaluation
        evidence: EvidenceEvaluation = self.evidence_engine.evaluate(
            complaint=complaint_info,
            match=match_result,
        )

        # Stage 5 — classification (case_type, department, severity, action)
        classification: ClassificationResult = self.classifier.classify(
            complaint=complaint_info,
            match=match_result,
            verdict=evidence.verdict,
        )

        # Stage 6 — routing decision
        routing: RoutingDecision = self.routing.decide(
            department=classification.department,
            severity=classification.severity,
            case_type=classification.case_type,
            needs_human_review=classification.needs_human,
        )

        # Stage 7 — final customer-facing response (SafetyEngine-wrapped)
        final: FinalResponse = self.response.compose(
            complaint=complaint_info,
            classification=classification,
            routing=routing,
            evidence=evidence,
            match=match_result,
        )

        # Stage 8 — human review ticket (built unconditionally; priority
        # reflects whether human review is actually required).
        review_ticket: ReviewTicket = self.review.build(
            ticket_id=req.ticket_id,
            customer_id=req.metadata.customer_id,
            complaint_text=complaint_info.raw_text,
            department=classification.department,
            severity=classification.severity,
            case_type=classification.case_type,
            action=routing.action,
            reason_codes=classification.reason_codes,
            suggested_reply=final.customer_reply,
            metadata={
                "channel": req.metadata.channel,
                "locale": req.metadata.locale,
                "submitted_at": (
                    req.metadata.submitted_at.isoformat()
                    if req.metadata.submitted_at
                    else None
                ),
            },
        )

        # Stage 9 — build the strict outbound envelope.
        reason_codes = _build_response_reason_codes(
            classification=classification,
            routing=routing,
            evidence=evidence,
            final=final,
        )

        relevant_tx_id = (
            match_result.transaction.transaction_id
            if match_result.matched and match_result.transaction
            else None
        )

        response = AnalyzeTicketResponse(
            ticket_id=req.ticket_id,
            relevant_transaction_id=relevant_tx_id,
            evidence_verdict=evidence.verdict,
            case_type=_map_case_type(classification.case_type),
            department=classification.department,
            severity=classification.severity,
            human_review_required=classification.needs_human,
            confidence=_clamp_confidence(
                classification.confidence, evidence.confidence
            ),
            reason_codes=reason_codes,
            recommended_next_action=routing.action,
            agent_summary=final.agent_summary,
            customer_reply=final.customer_reply,
            language_detected=_map_language(complaint_info.language.value),
            investigated_at=datetime.now(timezone.utc),
        )

        log.info(
            "investigation_done",
            extra={
                "ticket_id": req.ticket_id,
                "stage": "pipeline.done",
                "verdict": evidence.verdict.value,
                "case_type": classification.case_type.value,
                "action": routing.action.value,
                "needs_human": classification.needs_human,
                "safety_verified": final.safety_verified,
                "safety_rewritten": final.safety_rewritten,
                "llm_used": final.llm_used,
            },
        )

        # Stash the review ticket on the response for the route to read.
        # We do NOT include it in the wire payload — judges only see the
        # strict AnalyzeTicketResponse — but it stays available for the
        # debug endpoint and for tests.
        response.__dict__["_review_ticket"] = review_ticket  # type: ignore[attr-defined]

        return response


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


# Whitelist of reason codes that may appear in the outbound response.
# Anything else (e.g. routing's "base_action:..." or response's "safety_verified")
# is dropped here to keep the wire format strict.
_ALLOWED_REASON_CODES: frozenset[str] = frozenset({
    "duplicate_within_window",
    "amount_matches_complaint",
    "amount_mismatch",
    "type_matches_intent",
    "type_mismatch",
    "date_within_window",
    "date_outside_window",
    "no_transactions_provided",
    "multiple_candidates_tied",
    "no_candidate_above_threshold",
    "complaint_contains_phishing_signal",
    "complaint_contains_unauthorized_signal",
    "complaint_contains_duplicate_signal",
    "complaint_contains_failed_signal",
    "high_value_dispute",
    "critical_value_dispute",
    "language_bangla",
    "language_banglish",
    "language_english",
    "prompt_injection_detected",
    "llm_timeout_fallback",
    "safety_violation_rewritten",
    "rule_override_of_llm",
})


def _build_response_reason_codes(
    *,
    classification: ClassificationResult,
    routing: RoutingDecision,
    evidence: EvidenceEvaluation,
    final: FinalResponse,
) -> list[str]:
    """Compose the ordered, deduped reason-code list for the response.

    Order: classification -> routing -> evidence -> safety.
    Unknown codes are dropped so the wire-format stays strict.
    """
    seen: set[str] = set()
    out: list[str] = []
    dropped: list[str] = []
    for src in (
        classification.reason_codes,
        routing.reason_codes,
        evidence.reason_codes,
        final.safety_reason_codes,
    ):
        for code in src:
            if not code or code in seen:
                continue
            if code not in _ALLOWED_REASON_CODES:
                dropped.append(code)
                continue
            seen.add(code)
            out.append(code)
    if dropped:
        log.info(
            "response_reason_codes_dropped",
            extra={"stage": "response.build", "dropped": dropped},
        )
    # Cap at 20 (matches schema max_length)
    return out[:20]


def _clamp_confidence(*values: float) -> float:
    """Pick the minimum confidence across upstream stages."""
    if not values:
        return 0.0
    return max(0.0, min(1.0, min(values)))


def _map_language(lang: str) -> str:
    """Map internal LanguageEnum value -> response wire literal."""
    m = {
        "english": "en",
        "bangla": "bn",
        "banglish": "banglish",
    }
    return m.get(lang, "unknown")


# Map the internal OfficialCaseTypeEnum (8 values used by routing +
# deterministic templates) to the response wire-format CaseTypeEnum
# (7 values exposed to judges).
_OFFICIAL_TO_WIRE: dict[OfficialCaseTypeEnum, CaseTypeEnum] = {
    OfficialCaseTypeEnum.WRONG_TRANSFER: CaseTypeEnum.UNAUTHORIZED_TRANSACTION,
    OfficialCaseTypeEnum.PAYMENT_FAILED: CaseTypeEnum.FAILED_TRANSFER,
    OfficialCaseTypeEnum.REFUND_REQUEST: CaseTypeEnum.REFUND_REQUEST,
    OfficialCaseTypeEnum.DUPLICATE_PAYMENT: CaseTypeEnum.DUPLICATE_DEBIT,
    OfficialCaseTypeEnum.MERCHANT_SETTLEMENT_DELAY: CaseTypeEnum.GENERAL_INQUIRY,
    OfficialCaseTypeEnum.AGENT_CASH_IN_ISSUE: CaseTypeEnum.GENERAL_INQUIRY,
    OfficialCaseTypeEnum.PHISHING_OR_SOCIAL_ENGINEERING: CaseTypeEnum.PHISHING_REPORT,
    OfficialCaseTypeEnum.OTHER: CaseTypeEnum.GENERAL_INQUIRY,
}


def _map_case_type(official: OfficialCaseTypeEnum) -> CaseTypeEnum:
    """Internal OfficialCaseTypeEnum -> wire CaseTypeEnum.

    Falls back to GENERAL_INQUIRY for unknown values (defensive — the
    enum is closed so this should never trigger, but we keep the
    fallback so a future enum addition can't crash the pipeline).
    """
    return _OFFICIAL_TO_WIRE.get(official, CaseTypeEnum.GENERAL_INQUIRY)


__all__ = ["InvestigationPipeline"]
