"""Complaint analysis prompt.

The model receives the raw complaint text plus the detected language and
must emit a STRICT JSON object describing extracted entities. The JSON is
validated by `ComplaintAnalyzerService`; invalid output falls back to
rule-based extraction.
"""
from __future__ import annotations

import json
from typing import Any

from ..schemas.enums import IntentEnum, TransactionTypeEnum


SYSTEM_POLICY: str = (
    "You are a complaint-analysis module for a fintech support system. "
    "Your job is to extract structured signals from a free-text customer "
    "complaint written in English, Bangla, or Banglish (Romanized Bangla). "
    "Always respond with a single JSON object and nothing else. "
    "Never include explanations, apologies, or markdown."
)


_JSON_SCHEMA_HINT: str = json.dumps(
    {
        "intent": "one of " + ", ".join(i.value for i in IntentEnum),
        "language": "one of en | bn | banglish | unknown",
        "amount_bdt": "number or null — the most likely disputed amount in Taka",
        "transaction_type": "one of " + ", ".join(t.value for t in TransactionTypeEnum),
        "counterparty": "string or null — phone number, merchant id, or name mentioned",
        "phone_numbers": "list of strings — all phone numbers found in the text",
        "merchant_refs": "list of strings — merchant names or reference ids",
        "time_hint": "ISO-8601 timestamp or null if a specific time is mentioned",
        "issue_keywords": "list of lowercase strings — short tags (e.g. duplicate, failed)",
        "refund_intent": "boolean — true if the customer explicitly asks for money back",
        "fraud_indicators": "list of strings — phishing link, fake otp, scam call, etc.",
        "urgency_signals": "list of strings — words like 'urgent', 'immediately', 'now'",
        "confidence": "number between 0.0 and 1.0",
    },
    ensure_ascii=False,
)


def build_complaint_prompt(
    complaint: str,
    language_hint: str = "unknown",
    *,
    max_chars: int = 3000,
) -> str:
    """Compose the prompt. `complaint` is the customer text."""
    snippet = complaint.strip()
    if len(snippet) > max_chars:
        snippet = snippet[:max_chars] + "…"
    return (
        f"{SYSTEM_POLICY}\n\n"
        f"Language hint: {language_hint}\n"
        f"Complaint text:\n\"\"\"\n{snippet}\n\"\"\"\n\n"
        f"Extract the following fields and reply with JSON only:\n"
        f"{_JSON_SCHEMA_HINT}\n"
    )


__all__ = ["build_complaint_prompt"]