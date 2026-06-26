"""Smoke test for SafetyEngine.

Coverage matrix:
  Phase 1 (validate): one assertion per category
  Phase 2 (rewrite): one assertion per category + a clean-text case
  Phase 3 (verify): clean text passes, rewritten template also passes,
                     a raw violation fails
  Phase 4 (inspect): the unified entry point produces the right verdict
                     for clean, single-violation, multi-violation inputs
"""
from __future__ import annotations

import sys

from app.services.safety_engine import SafetyEngine


CASES = [
    # (label, text, expected reason codes)
    ("clean", "Thanks, we received your request and will follow up shortly.", []),
    ("otp", "Please share your OTP so we can verify.", ["safety_request_secret_echo_blocked"]),
    ("pin", "Enter your PIN to continue.", ["safety_request_secret_echo_blocked"]),
    ("password", "What is your password?", ["safety_request_secret_echo_blocked"]),
    ("cvv", "Send us your CVV.", ["safety_request_secret_echo_blocked"]),
    ("card", "Please share your card number.", ["safety_request_card_echo_blocked"]),
    (
        "long-card-number",
        "Your card 4111 1111 1111 1111 was charged.",
        ["safety_request_card_echo_blocked"],
    ),
    ("refund", "Your refund will be processed in 24 hours.", ["safety_promise_refund_blocked"]),
    ("recovery", "We will recover your account balance.", ["safety_promise_recovery_blocked"]),
    ("unblock", "Your account will be unblocked shortly.", ["safety_promise_unblock_blocked"]),
    (
        "whatsapp",
        "Please contact me on whatsapp +8801712345678 to resolve.",
        ["safety_unofficial_channel_blocked"],
    ),
    (
        "phone",
        "Call our agent at +8801912345678 for help.",
        ["safety_unofficial_channel_blocked"],
    ),
    (
        "non-bkash-url",
        "Visit https://example.com/refund for your money.",
        ["safety_unofficial_channel_blocked"],
    ),
    (
        "multi-violation",
        "We will recover your account. Share your OTP. WhatsApp +8801712345678.",
        [
            "safety_request_secret_echo_blocked",
            "safety_promise_recovery_blocked",
            "safety_unofficial_channel_blocked",
        ],
    ),
]


def main() -> int:
    engine = SafetyEngine()
    failures = 0

    print("=== Phase 1: validate ===")
    for label, text, expected in CASES:
        report = engine.validate(text)
        actual = report.reason_codes
        ok = actual == expected
        if not ok:
            failures += 1
        print(
            f"  [{'OK' if ok else 'FAIL'}] {label:18s} "
            f"got={actual!r:90s} expected={expected!r}"
        )

    print()
    print("=== Phase 2: rewrite ===")
    for label, text, expected in CASES:
        result = engine.rewrite(text)
        rewrote = result.rewritten
        uses_template = result.customer_reply.startswith("Thank you for contacting support")
        should_rewrite = bool(expected)
        ok = (rewrote == should_rewrite) and (uses_template == should_rewrite)
        if not ok:
            failures += 1
        print(
            f"  [{'OK' if ok else 'FAIL'}] {label:18s} "
            f"rewritten={rewrote} uses_template={uses_template}"
        )

    print()
    print("=== Phase 3: verify ===")
    verify_clean_ok, _ = engine.verify("Thanks, we received your request.")
    assert verify_clean_ok, "clean text should verify"

    verify_template_ok, _ = engine.verify(
        "Thank you for contacting support. We have received your request."
    )
    assert verify_template_ok, "safe template should verify"

    verify_violation_fail, reasons = engine.verify("Share your OTP.")
    assert not verify_violation_fail, "OTP text must fail verification"
    assert "safety_verification_failed" in reasons
    print("  [OK] clean text passes verification")
    print("  [OK] safe template passes verification")
    print("  [OK] violation text fails verification with reason")

    print()
    print("=== Phase 4: inspect (unified entry point) ===")
    for label, text, expected in CASES:
        verdict = engine.inspect(text)
        if not expected:
            # Clean text: not rewritten, verified, customer_reply == text
            ok = (
                not verdict.rewritten
                and verdict.verified
                and verdict.customer_reply == text
            )
        else:
            # Violation text: rewritten, verified (since template is safe),
            # customer_reply is the safe template
            ok = (
                verdict.rewritten
                and verdict.verified
                and verdict.customer_reply.startswith(
                    "Thank you for contacting support"
                )
            )
        if not ok:
            failures += 1
        print(
            f"  [{'OK' if ok else 'FAIL'}] {label:18s} "
            f"rewritten={verdict.rewritten} verified={verdict.verified} "
            f"reasons={verdict.reason_codes}"
        )

    # Defence-in-depth: even if the safe template itself somehow matched
    # a violation (it shouldn't), `inspect` would catch it. As a check,
    # run `inspect` on a text that's not the safe template but that has
    # only a card request — after rewriting, the reason codes should
    # include the card reason AND the verified code.
    verdict = engine.inspect("Send your card number.")
    assert verdict.rewritten is True
    assert verdict.verified is True
    assert "safety_request_card_echo_blocked" in verdict.reason_codes
    assert "safety_verified" in verdict.reason_codes
    print("  [OK] inspect emits both violation and verification reasons")

    print()
    if failures == 0:
        print("ALL ASSERTIONS PASSED")
        return 0
    print(f"{failures} FAILURES")
    return 1


if __name__ == "__main__":
    sys.exit(main())