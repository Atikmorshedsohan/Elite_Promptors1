"""EvidenceEngine — verdict + reason-codes + calibrated confidence.

Inputs (typed):
    ComplaintInfo, MatchResult

Outputs (typed):
    EvidenceEvaluation { verdict, confidence, reason_codes, decided_at }

This is the FIRST deterministic gate: if verdict=insufficient_data we must
short-circuit to human review regardless of how confident any LLM call was.
"""
from __future__ import annotations

from datetime import datetime, timezone

from pydantic import BaseModel, ConfigDict, Field

from ..rules import evidence_rules as rules
from ..schemas.complaint_info import ComplaintInfo
from ..schemas.enums import EvidenceVerdictEnum
from ..schemas.match_result import MatchResult
from ..utils.logger import get_logger

log = get_logger(__name__)


class EvidenceEvaluation(BaseModel):
    """Strict output of EvidenceEngine."""

    model_config = ConfigDict(extra="forbid")

    verdict: EvidenceVerdictEnum
    confidence: float = Field(..., ge=0.0, le=1.0)
    reason_codes: list[str] = Field(default_factory=list, max_length=20)
    decided_at: datetime

    def to_dict(self) -> dict:
        return self.model_dump(mode="json")


class EvidenceEngine:
    """Stateless evaluator. No LLM, no I/O."""

    def evaluate(
        self,
        complaint: ComplaintInfo,
        match: MatchResult,
    ) -> EvidenceEvaluation:
        verdict, confidence, reasons = rules.evaluate(complaint, match)
        log.info(
            "evidence_evaluated",
            extra={
                "stage": "evidence",
                "verdict": verdict.value,
                "confidence": confidence,
                "matched": match.matched,
            },
        )
        return EvidenceEvaluation(
            verdict=verdict,
            confidence=confidence,
            reason_codes=reasons,
            decided_at=datetime.now(tz=timezone.utc),
        )


__all__ = ["EvidenceEngine", "EvidenceEvaluation"]