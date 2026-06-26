"""ClassificationEngine — deterministic case classification + routing + severity + review.

Inputs (typed):
    ComplaintInfo, MatchResult, EvidenceVerdictEnum (via evidence flow)

Outputs (typed):
    ClassificationResult containing:
        case_type       (OfficialCaseTypeEnum)
        department      (DepartmentEnum)
        severity        (SeverityEnum)
        needs_human     (bool)
        reason_codes    (list[str])
        confidence      (float)
"""
from __future__ import annotations

from datetime import datetime, timezone

from pydantic import BaseModel, ConfigDict, Field

from ..config import get_settings
from ..rules import classification_rules as rules
from ..schemas.complaint_info import ComplaintInfo
from ..schemas.enums import (
    ActionEnum,
    DepartmentEnum,
    EvidenceVerdictEnum,
    OfficialCaseTypeEnum,
    SeverityEnum,
)
from ..schemas.match_result import MatchResult
from ..utils.logger import get_logger

log = get_logger(__name__)


class ClassificationResult(BaseModel):
    """Strict output of ClassificationEngine."""

    model_config = ConfigDict(extra="forbid")

    case_type: OfficialCaseTypeEnum
    department: DepartmentEnum
    severity: SeverityEnum
    needs_human: bool
    recommended_action: ActionEnum
    confidence: float = Field(..., ge=0.0, le=1.0)
    reason_codes: list[str] = Field(default_factory=list, max_length=20)
    decided_at: datetime

    def to_dict(self) -> dict:
        return self.model_dump(mode="json")


class ClassificationEngine:
    """Stateless rule engine. No LLM, no I/O."""

    def classify(
        self,
        complaint: ComplaintInfo,
        match: MatchResult,
        verdict: EvidenceVerdictEnum,
        *,
        amount_bdt: float | None = None,
    ) -> ClassificationResult:
        settings = get_settings()

        amount = amount_bdt if amount_bdt is not None else complaint.amount_bdt
        counterparty_is_agent = bool(
            complaint.counterparty and "agent" in complaint.counterparty.lower()
        )

        case_type = rules.classify(
            intent=complaint.intent,
            verdict=verdict,
            txn_type=complaint.transaction_type,
            has_fraud_signal=bool(complaint.fraud_indicators),
            counterparty_is_agent=counterparty_is_agent,
        )

        dept_label = rules.department_for(case_type)
        department = DepartmentEnum(dept_label)

        sev_label = rules.severity_for(
            case_type=case_type,
            amount_bdt=amount,
            verdict=verdict,
            has_fraud_signal=bool(complaint.fraud_indicators),
            high_value_threshold=settings.high_value_threshold_taka,
            critical_value_threshold=settings.critical_value_threshold_taka,
        )
        severity = SeverityEnum(sev_label)

        needs_human = rules.needs_human_review(
            severity=sev_label,
            verdict=verdict,
            confidence=match.confidence,
            min_confidence=settings.min_confidence_threshold,
        )

        action = ActionEnum.for_department(department)
        if needs_human and action != ActionEnum.ESCALATE_TO_AGENT:
            # Already routed, but if verdict is insufficient keep escalation.
            if verdict == EvidenceVerdictEnum.INSUFFICIENT_DATA:
                action = ActionEnum.ESCALATE_TO_AGENT

        reasons: list[str] = []
        if complaint.intent.value != "unknown":
            reasons.append(f"intent_{complaint.intent.value}")
        if complaint.fraud_indicators:
            reasons.append("complaint_contains_phishing_signal")
        if match.method in {"rule_tie_llm_break"}:
            reasons.append("multiple_candidates_tied")
        if match.matched is False:
            reasons.append("no_candidate_above_threshold")
        if amount is not None and amount >= settings.critical_value_threshold_taka:
            reasons.append("critical_value_dispute")
        elif amount is not None and amount >= settings.high_value_threshold_taka:
            reasons.append("high_value_dispute")
        if verdict == EvidenceVerdictEnum.INSUFFICIENT_DATA:
            reasons.append("no_candidate_above_threshold")

        confidence = match.confidence if match.matched else min(match.confidence, 0.4)

        log.info(
            "classification_decided",
            extra={
                "stage": "classifier",
                "verdict": verdict.value,
                "confidence": confidence,
            },
        )

        return ClassificationResult(
            case_type=case_type,
            department=department,
            severity=severity,
            needs_human=needs_human,
            recommended_action=action,
            confidence=confidence,
            reason_codes=reasons,
            decided_at=datetime.now(tz=timezone.utc),
        )


__all__ = ["ClassificationEngine", "ClassificationResult"]  # explicit export