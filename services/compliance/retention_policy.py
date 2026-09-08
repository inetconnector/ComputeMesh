"""Retention Policy Engine for ComputeMesh GDPR & DSA Data Lifecycle Management.

Defines explicit, purpose-driven retention categories, statutory triggers, duration limits,
and deletion/anonymization actions in strict compliance with:
- GDPR Art. 5(1)(e) (Storage Limitation)
- DSA Art. 30(5) (Trader traceability retention limited to 6 months post-contract termination)
- Commercial/Tax statutory retention requirements
- Zero-disk volatile prompt streaming guarantees
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
from enum import Enum
from typing import Any


class RetentionCategory(str, Enum):
    PROMPT_INFERENCE_DATA = "PROMPT_INFERENCE_DATA"
    DSA_TRADER_RECORDS = "DSA_TRADER_RECORDS"
    INACTIVE_DRAFT_PROFILES = "INACTIVE_DRAFT_PROFILES"
    SECURITY_AUDIT_LOGS = "SECURITY_AUDIT_LOGS"
    ACCOUNTING_TAX_RECORDS = "ACCOUNTING_TAX_RECORDS"


class RetentionAction(str, Enum):
    PURGE_IMMEDIATELY = "PURGE_IMMEDIATELY"
    DELETE = "DELETE"
    ANONYMIZE = "ANONYMIZE"


@dataclass(frozen=True)
class RetentionRule:
    category: RetentionCategory
    legal_basis: str
    trigger_event: str
    duration_days: int | None
    action: RetentionAction
    description: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "category": self.category.value,
            "legal_basis": self.legal_basis,
            "trigger_event": self.trigger_event,
            "duration_days": self.duration_days,
            "action": self.action.value,
            "description": self.description,
        }

    def is_expired(self, trigger_timestamp_iso: str, now: datetime | None = None) -> bool:
        if self.duration_days is None or self.duration_days <= 0:
            return True
        current_time = now or datetime.now(timezone.utc)
        try:
            cleaned = trigger_timestamp_iso.replace("Z", "+00:00")
            dt = datetime.fromisoformat(cleaned)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return (current_time - dt) > timedelta(days=self.duration_days)
        except Exception:
            return False


class RetentionEngine:
    """Manages statutory and security retention rules across ComputeMesh data categories."""

    DEFAULT_RULES: dict[RetentionCategory, RetentionRule] = {
        RetentionCategory.PROMPT_INFERENCE_DATA: RetentionRule(
            category=RetentionCategory.PROMPT_INFERENCE_DATA,
            legal_basis="GDPR Art. 5(1)(e) - Privacy by Design & Zero-Disk volatile processing",
            trigger_event="INFERENCE_STREAM_COMPLETED",
            duration_days=0,
            action=RetentionAction.PURGE_IMMEDIATELY,
            description="Prompts, generated tokens, and inference streams reside exclusively in volatile RAM and are purged immediately upon stream termination.",
        ),
        RetentionCategory.DSA_TRADER_RECORDS: RetentionRule(
            category=RetentionCategory.DSA_TRADER_RECORDS,
            legal_basis="DSA Art. 30(5) - Statutory trader traceability retention",
            trigger_event="CONTRACTUAL_RELATIONSHIP_TERMINATED",
            duration_days=180,  # 6 months as mandated by DSA Art. 30(5)
            action=RetentionAction.DELETE,
            description="Information obtained under DSA Art. 30 shall be stored for a maximum of 6 months after the contractual relationship with the trader has ended, and thereafter erased.",
        ),
        RetentionCategory.INACTIVE_DRAFT_PROFILES: RetentionRule(
            category=RetentionCategory.INACTIVE_DRAFT_PROFILES,
            legal_basis="GDPR Art. 5(1)(e) - Storage limitation for incomplete pre-contractual data",
            trigger_event="DRAFT_PROFILE_CREATED",
            duration_days=90,
            action=RetentionAction.DELETE,
            description="Incomplete draft provider profiles with no bound operational fleets or active contracts are erased after 90 days of inactivity.",
        ),
        RetentionCategory.SECURITY_AUDIT_LOGS: RetentionRule(
            category=RetentionCategory.SECURITY_AUDIT_LOGS,
            legal_basis="GDPR Art. 6(1)(f) - Legitimate interest in platform security and abuse prevention",
            trigger_event="AUDIT_EVENT_LOGGED",
            duration_days=365,
            action=RetentionAction.ANONYMIZE,
            description="Security audit log events are retained for 365 days for forensic tracking, after which identifying account hashes are anonymized.",
        ),
        RetentionCategory.ACCOUNTING_TAX_RECORDS: RetentionRule(
            category=RetentionCategory.ACCOUNTING_TAX_RECORDS,
            legal_basis="Commercial & Fiscal Code (HGB/AO) - Statutory accounting retention",
            trigger_event="FINANCIAL_TRANSACTION_RECORDED",
            duration_days=3650,  # 10 years
            action=RetentionAction.ANONYMIZE,
            description="Billing ledgers, transaction records, and tax-relevant invoicing references are retained according to statutory fiscal requirements.",
        ),
    }

    @classmethod
    def get_rule(cls, category: RetentionCategory) -> RetentionRule:
        return cls.DEFAULT_RULES[category]

    @classmethod
    def all_rules(cls) -> list[RetentionRule]:
        return list(cls.DEFAULT_RULES.values())
