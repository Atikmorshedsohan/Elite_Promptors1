"""Helper utilities. Stateless functions, safe to import anywhere."""
from __future__ import annotations

import re
import unicodedata
from datetime import datetime, timezone
from typing import Iterable

from .constants import (
    BALANCE_KEYWORDS,
    DUPLICATE_KEYWORDS,
    FAILED_TRANSFER_KEYWORDS,
    INJECTION_PATTERNS,
    INQUIRY_KEYWORDS,
    PHISHING_KEYWORDS,
    REFUND_KEYWORDS,
    UNAUTHORIZED_KEYWORDS,
)


# --- Bangla Unicode range ---
_BANGLA_RE = re.compile(r"[\u0980-\u09FF]")


def detect_language(text: str) -> str:
    """Return 'bn' | 'banglish' | 'en' | 'unknown'."""
    if not text:
        return "unknown"
    has_bangla = bool(_BANGLA_RE.search(text))
    lowered = text.lower()
    if has_bangla:
        return "bn"
    banglish_markers = (
        "taka", "tk", "amar", "apnar", "keno", "korte", "paisi", "paisi",
        "hoise", "hoysni", "kothao", "din", "din", "din", "din",
        "amar account", "amar number", "balance koto", "taka katse",
        "taka jabe", "taka geshe",
    )
    if any(m in lowered for m in banglish_markers):
        return "banglish"
    ascii_letters = sum(1 for c in text if c.isascii() and c.isalpha())
    if ascii_letters >= max(1, len(text) // 4):
        return "en"
    return "unknown"


def extract_amount(text: str) -> float | None:
    """Extract the first plausible BDT amount from free text."""
    if not text:
        return None
    patterns = [
        r"(?:tk|taka|৳)\s*([0-9][0-9,]*(?:\.[0-9]+)?)",
        r"([0-9][0-9,]*(?:\.[0-9]+)?)\s*(?:tk|taka|৳)",
        r"([0-9][0-9,]*(?:\.[0-9]+)?)",
    ]
    for pat in patterns:
        m = re.search(pat, text, flags=re.IGNORECASE)
        if m:
            try:
                return float(m.group(1).replace(",", ""))
            except (ValueError, IndexError):
                continue
    return None


def extract_keywords(text: str, *sets: Iterable[str]) -> list[str]:
    """Return lowercased tokens from `text` that appear in any of `sets`."""
    if not text:
        return []
    lowered = text.lower()
    found: list[str] = []
    for s in sets:
        for kw in s:
            if kw and kw in lowered and kw not in found:
                found.append(kw)
    return found


def contains_any(text: str, patterns: Iterable[str]) -> bool:
    """True if `text` matches any regex pattern."""
    if not text:
        return False
    for p in patterns:
        if re.search(p, text, flags=re.IGNORECASE):
            return True
    return False


def clamp(value: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, value))


def utcnow() -> datetime:
    return datetime.now(tz=timezone.utc)


def normalize_text(text: str) -> str:
    """Normalize whitespace and unicode; collapse injection attempts."""
    if not text:
        return ""
    nfkc = unicodedata.normalize("NFKC", text)
    return re.sub(r"\s+", " ", nfkc).strip()


def strip_injection(text: str) -> str:
    """Remove known prompt-injection markers. Returns cleaned text."""
    cleaned = text
    for p in INJECTION_PATTERNS:
        cleaned = re.sub(p, "[REDACTED]", cleaned, flags=re.IGNORECASE)
    return cleaned


__all__ = [
    "detect_language",
    "extract_amount",
    "extract_keywords",
    "contains_any",
    "clamp",
    "utcnow",
    "normalize_text",
    "strip_injection",
    "BALANCE_KEYWORDS",
    "DUPLICATE_KEYWORDS",
    "FAILED_TRANSFER_KEYWORDS",
    "INQUIRY_KEYWORDS",
    "PHISHING_KEYWORDS",
    "REFUND_KEYWORDS",
    "UNAUTHORIZED_KEYWORDS",
]  # re-export for convenience