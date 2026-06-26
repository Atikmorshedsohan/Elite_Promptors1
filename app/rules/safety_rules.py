"""Pure safety-engine rules.

Categorized violation detection so the engine can emit a precise
reason code per category instead of a single opaque "rewritten" flag.

Categories:
    1. Secret request   - asking for OTP / PIN / password / CVV
    2. Card request     - asking for card number / card details
    3. Refund promise   - promising a refund / money-back
    4. Recovery promise - promising account / money recovery
    5. Unblock promise  - promising account unblock
    6. Unofficial channel - sending customer outside official channels

The functions are pure. They return a list of reason codes rather than
mutating input. The SafetyEngine service wraps them and decides whether
to rewrite.
"""
from __future__ import annotations

import re
from typing import Iterable

from app.utils.constants import (
    SAFETY_REASON_PROMISE_RECOVERY,
    SAFETY_REASON_PROMISE_REFUND,
    SAFETY_REASON_PROMISE_UNBLOCK,
    SAFETY_REASON_REQUEST_CARD,
    SAFETY_REASON_REQUEST_SECRET,
    SAFETY_REASON_UNOFFICIAL_CHANNEL,
    UNSAFE_ACCOUNT_RECOVERY_PATTERNS,
    UNSAFE_CARD_PATTERNS,
    UNSAFE_PROMISE_PATTERNS,
    UNSAFE_REQUEST_PATTERNS,
    UNSAFE_UNOFFICIAL_CHANNEL_PATTERNS,
)


def _matches(text: str, patterns: Iterable[str]) -> bool:
    """True if any pattern matches anywhere in `text`."""
    if not text:
        return False
    for p in patterns:
        if re.search(p, text, flags=re.IGNORECASE):
            return True
    return False


def detect_secret_request(text: str) -> bool:
    """OTP / PIN / password / CVV / seed phrase / recovery phrase."""
    return _matches(text, UNSAFE_REQUEST_PATTERNS)


def detect_card_request(text: str) -> bool:
    """Asking for card number / card details."""
    return _matches(text, UNSAFE_CARD_PATTERNS)


def detect_refund_promise(text: str) -> bool:
    """Sub-pattern: explicit refund / money-back promise."""
    refund_specific = (
        r"\brefund\s+(?:will|has|is|approved)\b",
        r"\bmoney\s+(?:will\s+be\s+)?refunded\b",
        r"\bguarantee(d)?\s+refund\b",
    )
    return _matches(text, refund_specific)


def detect_recovery_promise(text: str) -> bool:
    """Account / money recovery promise."""
    return _matches(text, UNSAFE_ACCOUNT_RECOVERY_PATTERNS)


def detect_unblock_promise(text: str) -> bool:
    """Account unblock promise. Sub-pattern of UNSAFE_PROMISE_PATTERNS
    but reported under its own category."""
    return _matches(text, (r"\baccount\s+(?:will\s+be\s+)?unblocked\b",))


def detect_unofficial_channel(text: str) -> bool:
    """Anything pointing the customer off-platform (raw phone numbers,
    third-party messengers, non-bkash URLs, in-person meetups)."""
    return _matches(text, UNSAFE_UNOFFICIAL_CHANNEL_PATTERNS)


def classify_violations(text: str) -> list[str]:
    """Return an ordered list of reason codes for every category hit.

    Order is deterministic (request categories first, then promises,
    then channel) so the audit trail is reproducible.
    """
    reasons: list[str] = []
    if detect_secret_request(text):
        reasons.append(SAFETY_REASON_REQUEST_SECRET)
    if detect_card_request(text):
        reasons.append(SAFETY_REASON_REQUEST_CARD)
    if detect_refund_promise(text):
        reasons.append(SAFETY_REASON_PROMISE_REFUND)
    if detect_recovery_promise(text):
        reasons.append(SAFETY_REASON_PROMISE_RECOVERY)
    if detect_unblock_promise(text):
        reasons.append(SAFETY_REASON_PROMISE_UNBLOCK)
    if detect_unofficial_channel(text):
        reasons.append(SAFETY_REASON_UNOFFICIAL_CHANNEL)
    return reasons


def any_violation(text: str) -> bool:
    """Cheap predicate — True if *any* safety category is triggered."""
    return (
        detect_secret_request(text)
        or detect_card_request(text)
        or detect_refund_promise(text)
        or detect_recovery_promise(text)
        or detect_unblock_promise(text)
        or detect_unofficial_channel(text)
    )


# --- Backwards-compat shim for the original SafetyService API ---
# The legacy blocklist had a single "request" bucket covering
# OTP/PIN/CVV and a single "promise" bucket covering refund/unblock.
# These helpers reproduce that surface so legacy callers keep working.

def has_legacy_request_violation(text: str) -> bool:
    return detect_secret_request(text) or detect_card_request(text)


def has_legacy_promise_violation(text: str) -> bool:
    if detect_refund_promise(text) or detect_unblock_promise(text):
        return True
    # Recovery-promise text also triggers a generic guarantee in the
    # legacy blocklist via UNSAFE_PROMISE_PATTERNS.
    return _matches(text, UNSAFE_PROMISE_PATTERNS)
