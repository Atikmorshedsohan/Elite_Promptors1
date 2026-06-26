"""ComplaintAnalyzerService — extract structured signals from complaint text.

Pipeline:
  1. Detect language (rules + Unicode range).
  2. Rule-based extraction (fast, deterministic, always runs).
  3. LLM-based extraction (only when rules yield low confidence OR explicit
     hybrid mode).
  4. Merge with strict precedence: LLM wins for `intent`, rules win for
     `amount` when LLM omits it, enum validation always enforced.
  5. Return validated `ComplaintInfo`.
"""
from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from typing import Any

from pydantic import ValidationError

from ..ai.llm_client import LLMClient
from ..ai.prompt_manager import get_prompt
from ..config import get_settings
from ..schemas.complaint_info import ComplaintInfo
from ..schemas.enums import (
    IntentEnum,
    LanguageEnum,
    TransactionTypeEnum,
)
from ..utils.constants import (
    BALANCE_KEYWORDS,
    DUPLICATE_KEYWORDS,
    FAILED_TRANSFER_KEYWORDS,
    INQUIRY_KEYWORDS,
    INJECTION_PATTERNS,
    PHISHING_KEYWORDS,
    REFUND_KEYWORDS,
    UNAUTHORIZED_KEYWORDS,
)
from ..utils.helpers import (
    clamp,
    contains_any,
    detect_language,
    extract_amount,
    extract_keywords,
    strip_injection,
)
from ..utils.logger import get_logger

log = get_logger(__name__)


_PHONE_RE = re.compile(r"\+?880\d{10}|0\d{10}|\b\d{11}\b")
_MERCHANT_HINT_RE = re.compile(r"(?:merchant|shop|store|vendor)\s*[:\-]?\s*([A-Za-z0-9_\- ]{2,40})", re.IGNORECASE)
_URGENCY_RE = re.compile(r"\b(urgent|urgently|immediately|right now|asap|এখনই|জরুরি|তাড়াতাড়ি)\b", re.IGNORECASE)
_TIME_HINT_RE = re.compile(
    r"\b(\d{4}-\d{2}-\d{2}[T\s]\d{2}:\d{2}(?::\d{2})?(?:Z|[+\-]\d{2}:?\d{2})?)\b"
)
_TIME_HINT_BN_RE = re.compile(
    r"\b(\d{1,2}[/\-]\d{1,2}[/\-]\d{2,4})(?:[ T](\d{1,2}:\d{2}(?::\d{2})?))?\b"
)


class ComplaintAnalyzerService:
    """Hybrid complaint analyzer: rules-first, LLM assist on ambiguity."""

    def __init__(self, llm: LLMClient) -> None:
        self._llm = llm
        self._settings = get_settings()

    # ---- Public API ----

    def analyze(self, complaint: str) -> ComplaintInfo:
        """Analyze complaint text. Never raises."""
        cleaned = strip_injection(complaint or "")
        language = LanguageEnum.from_label(detect_language(cleaned))

        rule_info = self._rule_based(cleaned, language)
        needs_llm = (
            rule_info.confidence < self._settings.min_confidence_threshold
            or rule_info.intent == IntentEnum.UNKNOWN
        )

        if not needs_llm:
            log.info(
                "complaint_analyzed_rules",
                extra={"stage": "complaint_analyzer", "confidence": rule_info.confidence},
            )
            return rule_info

        llm_raw = self._llm_extract(cleaned, language)
        merged = self._merge(rule_info, llm_raw, language)
        log.info(
            "complaint_analyzed_hybrid",
            extra={"stage": "complaint_analyzer", "confidence": merged.confidence},
        )
        return merged

    # ---- Stage 1: rule-based ----

    def _rule_based(self, text: str, language: LanguageEnum) -> ComplaintInfo:
        lowered = text.lower()
        amount = extract_amount(text)
        phones = list(dict.fromkeys(_PHONE_RE.findall(text)))
        merchants = list(dict.fromkeys(m.strip() for m in _MERCHANT_HINT_RE.findall(text) if m.strip()))

        intent = self._classify_intent(lowered)
        txn_type = self._classify_txn_type(lowered)
        refund = bool(extract_keywords(text, REFUND_KEYWORDS))

        fraud: list[str] = []
        if contains_any(text, PHISHING_KEYWORDS):
            fraud.append("phishing_signal")
        if contains_any(text, UNAUTHORIZED_KEYWORDS):
            fraud.append("unauthorized_signal")

        time_hint = self._parse_time_hint(text)
        urgency = list(dict.fromkeys(_URGENCY_RE.findall(text)))

        keywords: list[str] = []
        keywords.extend(extract_keywords(text, DUPLICATE_KEYWORDS))
        keywords.extend(extract_keywords(text, FAILED_TRANSFER_KEYWORDS))
        keywords.extend(extract_keywords(text, BALANCE_KEYWORDS))
        keywords.extend(extract_keywords(text, INQUIRY_KEYWORDS))

        # Confidence: high when intent and amount both extracted, else low.
        confidence = 0.0
        if intent != IntentEnum.UNKNOWN:
            confidence += 0.5
        if amount is not None:
            confidence += 0.3
        if phones or merchants:
            confidence += 0.1
        if fraud:
            confidence += 0.1
        confidence = clamp(confidence, 0.0, 1.0)

        return ComplaintInfo(
            raw_text=text,
            language=language,
            intent=intent,
            transaction_type=txn_type,
            amount_bdt=amount,
            counterparty=(phones[0] if phones else (merchants[0] if merchants else None)),
            phone_numbers=phones,
            merchant_refs=merchants,
            time_hint=time_hint,
            issue_keywords=keywords,
            refund_intent=refund,
            fraud_indicators=fraud,
            urgency_signals=urgency,
            confidence=confidence,
            source="rules",
        )

    def _classify_intent(self, lowered: str) -> IntentEnum:
        if contains_any(lowered, DUPLICATE_KEYWORDS):
            return IntentEnum.DUPLICATE_DEBIT
        if contains_any(lowered, FAILED_TRANSFER_KEYWORDS):
            return IntentEnum.FAILED_TRANSFER
        if contains_any(lowered, UNAUTHORIZED_KEYWORDS):
            return IntentEnum.UNAUTHORIZED_TRANSACTION
        if contains_any(lowered, PHISHING_KEYWORDS):
            return IntentEnum.PHISHING_REPORT
        if contains_any(lowered, REFUND_KEYWORDS):
            return IntentEnum.REFUND_REQUEST
        if contains_any(lowered, BALANCE_KEYWORDS):
            return IntentEnum.BALANCE_INQUIRY
        if contains_any(lowered, INQUIRY_KEYWORDS):
            return IntentEnum.GENERAL_INQUIRY
        return IntentEnum.UNKNOWN

    def _classify_txn_type(self, lowered: str) -> TransactionTypeEnum | None:
        if any(w in lowered for w in ("send money", "send_money", "পাঠানো", "পাঠাই", "পাঠিয়েছি")):
            return TransactionTypeEnum.SEND_MONEY
        if any(w in lowered for w in ("cash out", "cashout", "উত্তোলন", "ক্যাশ আউট")):
            return TransactionTypeEnum.CASH_OUT
        if any(w in lowered for w in ("payment", "bill", "বিল", "পেমেন্ট", "মার্চেন্ট")):
            return TransactionTypeEnum.PAYMENT
        if any(w in lowered for w in ("deposit", "add money", "জমা", "ডিপোজিট")):
            return TransactionTypeEnum.DEPOSIT
        if any(w in lowered for w in ("fee", "ফি", "চার্জ")):
            return TransactionTypeEnum.FEE
        if any(w in lowered for w in ("reversal", "refund", "ফেরত", "রিভার্স")):
            return TransactionTypeEnum.REVERSAL
        return None

    def _parse_time_hint(self, text: str) -> datetime | None:
        m = _TIME_HINT_RE.search(text)
        if m:
            try:
                dt = datetime.fromisoformat(m.group(1).replace("Z", "+00:00"))
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=timezone.utc)
                return dt
            except ValueError:
                pass
        m = _TIME_HINT_BN_RE.search(text)
        if m:
            date_str = m.group(1).replace("-", "/")
            time_str = m.group(2) or "00:00:00"
            try:
                fmt = "%Y/%m/%d" if len(date_str.split("/")[-1]) == 4 else "%d/%m/%Y"
                dt = datetime.strptime(f"{date_str} {time_str}", f"{fmt} %H:%M:%S")
                return dt.replace(tzinfo=timezone.utc)
            except ValueError:
                pass
        return None

    # ---- Stage 2: LLM extraction ----

    def _llm_extract(self, text: str, language: LanguageEnum) -> dict[str, Any]:
        prompt = get_prompt("complaint")(text, language.value)
        raw = self._llm.safe_generate(prompt, expect_json=True)
        if not raw:
            return {}
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            log.warning("complaint_llm_bad_json", extra={"stage": "complaint_analyzer"})
            return {}
        return data if isinstance(data, dict) else {}

    # ---- Stage 3: merge ----

    def _merge(
        self, rules: ComplaintInfo, llm: dict[str, Any], language: LanguageEnum
    ) -> ComplaintInfo:
        merged: dict[str, Any] = rules.model_dump(mode="json")
        merged["source"] = "hybrid"
        merged["language"] = language

        if llm:
            intent_raw = llm.get("intent")
            if isinstance(intent_raw, str):
                try:
                    merged["intent"] = IntentEnum(intent_raw).value
                except ValueError:
                    pass
            type_raw = llm.get("transaction_type")
            if isinstance(type_raw, str):
                try:
                    merged["transaction_type"] = TransactionTypeEnum(type_raw).value
                except ValueError:
                    pass
            amt = llm.get("amount_bdt")
            if isinstance(amt, (int, float)) and amt > 0 and not rules.has_amount():
                merged["amount_bdt"] = float(amt)
            cp = llm.get("counterparty")
            if isinstance(cp, str) and not rules.has_counterparty():
                merged["counterparty"] = cp.strip()
            for field in ("phone_numbers", "merchant_refs", "issue_keywords",
                          "fraud_indicators", "urgency_signals"):
                vals = llm.get(field)
                if isinstance(vals, list):
                    existing = set(merged.get(field, []))
                    for v in vals:
                        if isinstance(v, str) and v.strip() and v not in existing:
                            merged[field].append(v.strip())
                            existing.add(v.strip())
            refund = llm.get("refund_intent")
            if isinstance(refund, bool):
                merged["refund_intent"] = merged["refund_intent"] or refund
            conf = llm.get("confidence")
            if isinstance(conf, (int, float)):
                merged["confidence"] = clamp(
                    (rules.confidence + float(conf)) / 2.0, 0.0, 1.0
                )
            time_hint = llm.get("time_hint")
            if isinstance(time_hint, str) and not merged.get("time_hint"):
                try:
                    dt = datetime.fromisoformat(time_hint.replace("Z", "+00:00"))
                    if dt.tzinfo is None:
                        dt = dt.replace(tzinfo=timezone.utc)
                    merged["time_hint"] = dt.isoformat()
                except ValueError:
                    pass

        # Re-validate via the typed model.
        try:
            return ComplaintInfo.model_validate(merged)
        except ValidationError as exc:
            log.warning(
                "complaint_merge_invalid_falling_back_to_rules",
                extra={"stage": "complaint_analyzer"},
            )
            return rules


__all__ = ["ComplaintAnalyzerService"]  # explicit export