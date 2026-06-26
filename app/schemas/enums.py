"""Strict enums for the entire pipeline. Code-enforced everywhere.

These values are part of the public API contract — never rename or remove
a member without bumping `schema_version` in `response.py`.
"""
from __future__ import annotations

from enum import Enum


class LanguageEnum(str, Enum):
    """Detected language of the complaint text."""
    ENGLISH = "en"
    BANGLA = "bn"
    BANGLISH = "banglish"
    UNKNOWN = "unknown"

    @classmethod
    def from_label(cls, label: str | None) -> "LanguageEnum":
        if not label:
            return cls.UNKNOWN
        norm = label.strip().lower()
        aliases = {
            "english": cls.ENGLISH, "en": cls.ENGLISH, "eng": cls.ENGLISH,
            "bangla": cls.BANGLA, "bn": cls.BANGLA, "বাংলা": cls.BANGLA,
            "banglish": cls.BANGLISH, "benglish": cls.BANGLISH,
        }
        return aliases.get(norm, cls.UNKNOWN)


class IntentEnum(str, Enum):
    DUPLICATE_DEBIT = "duplicate_debit"
    FAILED_TRANSFER = "failed_transfer"
    UNAUTHORIZED_TRANSACTION = "unauthorized_transaction"
    PHISHING_REPORT = "phishing_report"
    REFUND_REQUEST = "refund_request"
    BALANCE_INQUIRY = "balance_inquiry"
    GENERAL_INQUIRY = "general_inquiry"
    UNKNOWN = "unknown"


class TransactionTypeEnum(str, Enum):
    SEND_MONEY = "send_money"
    CASH_OUT = "cash_out"
    CASH_IN = "cash_in"
    PAYMENT = "payment"
    FEE = "fee"
    REVERSAL = "reversal"
    DEPOSIT = "deposit"
    OTHER = "other"


class EvidenceVerdictEnum(str, Enum):
    CONSISTENT = "consistent"
    INCONSISTENT = "inconsistent"
    INSUFFICIENT_DATA = "insufficient_data"


class CaseTypeEnum(str, Enum):
    """Internal taxonomy used during reasoning.

    Kept for backward compatibility with earlier drafts. The **official**
    public-API vocabulary lives in `OfficialCaseTypeEnum` below; the
    ClassificationEngine emits that enum, not this one.
    """
    DUPLICATE_DEBIT = "duplicate_debit"
    FAILED_TRANSFER = "failed_transfer"
    UNAUTHORIZED_TRANSACTION = "unauthorized_transaction"
    PHISHING_REPORT = "phishing_report"
    REFUND_REQUEST = "refund_request"
    BALANCE_INQUIRY = "balance_inquiry"
    GENERAL_INQUIRY = "general_inquiry"


class OfficialCaseTypeEnum(str, Enum):
    """Authoritative public-API case-type vocabulary.

    These 8 labels are fixed by the competition and MUST appear verbatim
    in `case_type` on the response. Never rename; never remove.
    """
    WRONG_TRANSFER = "wrong_transfer"
    PAYMENT_FAILED = "payment_failed"
    REFUND_REQUEST = "refund_request"
    DUPLICATE_PAYMENT = "duplicate_payment"
    MERCHANT_SETTLEMENT_DELAY = "merchant_settlement_delay"
    AGENT_CASH_IN_ISSUE = "agent_cash_in_issue"
    PHISHING_OR_SOCIAL_ENGINEERING = "phishing_or_social_engineering"
    OTHER = "other"

    @classmethod
    def from_internal(
        cls,
        internal: CaseTypeEnum | str | None,
        *,
        verdict: "EvidenceVerdictEnum | str | None" = None,
    ) -> "OfficialCaseTypeEnum":
        """Map internal taxonomy + verdict into the official 8-label set."""
        if internal is None:
            return cls.OTHER
        key = internal.value if isinstance(internal, CaseTypeEnum) else str(internal)
        mapping = {
            "duplicate_debit": cls.DUPLICATE_PAYMENT,
            "duplicate_payment": cls.DUPLICATE_PAYMENT,
            "failed_transfer": cls.PAYMENT_FAILED,
            "payment_failed": cls.PAYMENT_FAILED,
            "unauthorized_transaction": cls.WRONG_TRANSFER,
            "phishing_report": cls.PHISHING_OR_SOCIAL_ENGINEERING,
            "refund_request": cls.REFUND_REQUEST,
            "balance_inquiry": cls.OTHER,
            "general_inquiry": cls.OTHER,
        }
        return mapping.get(key, cls.OTHER)


class DepartmentEnum(str, Enum):
    """Operational department the case is routed to."""
    PAYMENTS = "payments"
    DISPUTES = "disputes"
    FRAUD_RISK = "fraud_risk"
    CUSTOMER_SUCCESS = "customer_success"
    TECHNICAL_SUPPORT = "technical_support"

    @property
    def display(self) -> str:
        return self.value.replace("_", " ").title()


class SeverityEnum(str, Enum):
    """Case severity ordered low → critical."""
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"

    @classmethod
    def order(cls) -> list["SeverityEnum"]:
        return [cls.LOW, cls.MEDIUM, cls.HIGH, cls.CRITICAL]

    def rank(self) -> int:
        return self.order().index(self)

    def is_high_or_above(self) -> bool:
        return self.rank() >= self.order().index(SeverityEnum.HIGH)


class ActionEnum(str, Enum):
    """Operational next-action verbs. Snake_case, stable."""
    ESCALATE_TO_AGENT = "escalate_to_agent"
    ROUTE_TO_DISPUTES = "route_to_disputes"
    ROUTE_TO_FRAUD = "route_to_fraud"
    ROUTE_TO_PAYMENTS = "route_to_payments"
    ROUTE_TO_CUSTOMER_SUCCESS = "route_to_customer_success"
    ROUTE_TO_TECHNICAL = "route_to_technical"
    REQUEST_MORE_INFO = "request_more_info"
    NO_ACTION_REQUIRED = "no_action_required"

    @classmethod
    def for_department(cls, dept: DepartmentEnum) -> "ActionEnum":
        mapping = {
            DepartmentEnum.PAYMENTS: cls.ROUTE_TO_PAYMENTS,
            DepartmentEnum.DISPUTES: cls.ROUTE_TO_DISPUTES,
            DepartmentEnum.FRAUD_RISK: cls.ROUTE_TO_FRAUD,
            DepartmentEnum.CUSTOMER_SUCCESS: cls.ROUTE_TO_CUSTOMER_SUCCESS,
            DepartmentEnum.TECHNICAL_SUPPORT: cls.ROUTE_TO_TECHNICAL,
        }
        return mapping.get(dept, cls.ESCALATE_TO_AGENT)