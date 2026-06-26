"""Project-wide constants. Pure data, zero logic."""
from __future__ import annotations

# --- Bangla / Banglish / English keywords (lowercased) ---

DUPLICATE_KEYWORDS: set[str] = {
    "duplicate", "twice", "double", "two times", "2 times", "again",
    "dobble", "dublicate", "duita", "à¦¦à§à¦‡à¦¬à¦¾à¦°", "à¦¦à§à¦¬à¦¾à¦°", "à¦¡à§à¦ªà§à¦²à¦¿à¦•à§‡à¦Ÿ",
    "à¦à¦•à¦‡", "à¦†à¦¬à¦¾à¦°", "à¦¡à¦¾à¦¬à¦²",
}

FAILED_TRANSFER_KEYWORDS: set[str] = {
    "failed", "didn't go", "did not go", "not received", "not credited",
    "transfer fail", "send but not", "sent but not",
    "à¦¹à¦¯à¦¼à¦¨à¦¿", "à¦¬à§à¦¯à¦°à§à¦¥", "à¦ªà¦¾à¦ à¦¾à¦¨à§‹ à¦¹à¦¯à¦¼à¦¨à¦¿", "à¦ªà§‡à¦¯à¦¼à§‡à¦›à¦¿ à¦¨à¦¾", "à¦¯à¦¾à¦¯à¦¼à¦¨à¦¿", "à¦«à§‡à¦‡à¦²",
}

UNAUTHORIZED_KEYWORDS: set[str] = {
    "unauthorized", "not me", "didn't do", "did not do", "i didn't", "i did not",
    "not my transaction", "fraud", "stolen",
    "à¦†à¦®à¦¿ à¦•à¦°à¦¿à¦¨à¦¿", "à¦†à¦®à¦¿ à¦•à¦°à¦¿ à¦¨à¦¾à¦‡", "à¦šà§à¦°à¦¿", "à¦…à¦¨à¦¨à§à¦®à§‹à¦¦à¦¿à¦¤", "à¦¹à§à¦¯à¦¾à¦•",
}

PHISHING_KEYWORDS: set[str] = {
    "phishing", "phish", "fake link", "fraud link", "otp asked",
    "pin asked", "password asked", "scam call", "scam message",
    "à¦«à¦¿à¦¶à¦¿à¦‚", "à¦­à§à¦¯à¦¼à¦¾ à¦²à¦¿à¦‚à¦•", "à¦ªà§à¦°à¦¤à¦¾à¦°à¦£à¦¾", "à¦¸à§à¦•à§à¦¯à¦¾à¦®",
}

REFUND_KEYWORDS: set[str] = {
    "refund", "money back", "return my money", "reverse",
    "à¦«à§‡à¦°à¦¤", "à¦Ÿà¦¾à¦•à¦¾ à¦«à§‡à¦°à¦¤", "à¦°à¦¿à¦«à¦¾à¦¨à§à¦¡",
}

BALANCE_KEYWORDS: set[str] = {
    "balance", "balence", "blance", "how much", "remaining",
    "à¦¬à§à¦¯à¦¾à¦²à§‡à¦¨à§à¦¸", "à¦•à¦¤ à¦Ÿà¦¾à¦•à¦¾", "à¦Ÿà¦¾à¦•à¦¾ à¦†à¦›à§‡",
}

INQUIRY_KEYWORDS: set[str] = {
    "help", "support", "issue", "problem", "question",
    "à¦¸à¦¾à¦¹à¦¾à¦¯à§à¦¯", "à¦¸à¦®à¦¸à§à¦¯à¦¾", "à¦ªà§à¦°à¦¶à§à¦¨",
}

# --- Safety blocklist (regex patterns, case-insensitive) ---

UNSAFE_REQUEST_PATTERNS: tuple[str, ...] = (
    # Imperative verb + possessive pronoun + secret token.
    r"(?:send|share|provide|give|tell|forward|submit|enter|type)\s+(?:your|the|my)\s+(?:otp|one[-\s]?time[-\s]?password|pin|password|cvv|seed\s*phrase|recovery\s*phrase)",
    # Bare imperative (no pronoun): "send OTP" / "share PIN".
    r"(?:send|share|provide|give|tell|forward|submit|enter)\s+(?:your|the|my|me|us)(?:\s+(?:your|the|my))?\s+(?:otp|pin|password|cvv)\b",
    # Asking: "what is your OTP" / "where is my PIN".
    r"(?:what|where)[\s\S]{0,30}\b(?:otp|pin|password|cvv)\b",
    # Verification scam phrases.
    r"verify\s+(?:your|the)\s+(?:otp|pin|password|account)",
    r"confirm\s+(?:your|the)\s+(?:otp|pin|password|cvv)",
)

UNSAFE_PROMISE_PATTERNS: tuple[str, ...] = (
    r"\brefund\s+(?:will|has|is|approved)\b",
    r"\bmoney\s+(?:will\s+be\s+)?refunded\b",
    r"\breversal\s+(?:will|has|is|approved)\b",
    r"\baccount\s+(?:will\s+be\s+)?unblocked\b",
    r"\brecovered\b",
    r"\bguarantee(d)?\s+refund\b",
)

# --- Safe template fallback (used when LLM output violates Safety Guard) ---

SAFE_REPLY_TEMPLATE: str = (
    "Thank you for contacting support. We have received your request "
    "and an agent will review it through official channels. "
    "If eligible, the matter will be investigated and you will be contacted "
    "with the outcome. Please do not share OTP, PIN, or passwords with anyone."
)

SAFE_SUMMARY_TEMPLATE: str = (
    "Customer submitted a complaint. The case has been logged and routed for "
    "human review based on the available evidence. No automated resolution "
    "has been issued."
)

SAFE_ACTION_TEMPLATE: str = "escalate_to_agent"

# --- Injection guard ---

INJECTION_PATTERNS: tuple[str, ...] = (
    r"ignore\s+(?:all\s+)?previous\s+instructions",
    r"disregard\s+(?:all\s+)?prior",
    r"you\s+are\s+now",
    r"system\s*prompt",
    r"reveal\s+(?:the\s+)?prompt",
    r"act\s+as\s+(?:a\s+)?(?:developer|admin|root)",
)


# --- SafetyEngine blocklists (categorized for per-reason auditing) ---

UNSAFE_CARD_PATTERNS = (
    r"\bcard\s*(?:number|no\.?|no)\b",
    r"\bcredit\s*card\s*(?:number|no\.?|no)\b",
    r"\bdebit\s*card\s*(?:number|no\.?|no)\b",
    r"\bcard\s+(?:details|info|information)\b",
    # Generic 13-19 digit PAN, optionally space- or dash-separated in 4s.
    r"\b\d{4}[\s-]?\d{4}[\s-]?\d{4}[\s-]?\d{4}\b",
    r"\bsend\s+(?:your|the)\s+card\b",
    r"\bprovide\s+(?:your|the)\s+card\b",
)

UNSAFE_ACCOUNT_RECOVERY_PATTERNS = (
    r"\baccount\s+(?:will\s+be\s+)?(?:recovered|restored|reactivated)\b",
    r"\bmoney\s+(?:will\s+be\s+)?recovered\b",
    r"\bbalance\s+(?:will\s+be\s+)?restored\b",
    r"\bwe\s+(?:can|will)\s+recover\b",
    r"\b(?:we|support)\s+(?:can|will)\s+(?:restore|reactivate)\b",
)

UNSAFE_UNOFFICIAL_CHANNEL_PATTERNS = (
    r"\b(?:contact|call|reach|message)\b[^\n]{0,40}\b(?:whatsapp|telegram|viber|signal|gmail|yahoo|hotmail|outlook)\b",
    # Bangladesh mobile: 01[3-9]XXXXXXXX (11 digits), with optional +88 country code.
    r"\b(?:\+?88)?01[3-9]\d{8}\b",
    # Any non-bkash URL.
    r"\bhttps?://(?!bkash)[\w.-]+\.[a-z]{2,}\b",
    r"\bmeet\s+(?:me|us)\s+(?:in\s+person|outside|at)\b",
    r"\bsend\s+(?:me|us|your)?\s*(?:a\s+)?(?:photo|picture|selfie|video)\b",
    r"\bshare\s+(?:me|us|your)?\s*(?:a\s+)?(?:photo|picture|selfie|video)\b",
)

SAFETY_REASON_REQUEST_SECRET = "safety_request_secret_echo_blocked"
SAFETY_REASON_REQUEST_CARD = "safety_request_card_echo_blocked"
SAFETY_REASON_PROMISE_REFUND = "safety_promise_refund_blocked"
SAFETY_REASON_PROMISE_RECOVERY = "safety_promise_recovery_blocked"
SAFETY_REASON_PROMISE_UNBLOCK = "safety_promise_unblock_blocked"
SAFETY_REASON_UNOFFICIAL_CHANNEL = "safety_unofficial_channel_blocked"
SAFETY_REASON_TRUNCATED = "safety_truncated"
SAFETY_REASON_VERIFIED = "safety_verified"
SAFETY_REASON_VERIFICATION_FAILED = "safety_verification_failed"

SAFETY_REPLY_MAX_LEN = 1000
SAFETY_SUMMARY_MAX_LEN = 2000
