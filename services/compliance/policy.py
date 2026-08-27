"""Fail-closed production compliance controls.

These controls are engineering safeguards, not a legal determination. Development and
research paths remain available unless COMPUTEMESH_PRODUCTION_MODE=1 is set.
"""
from __future__ import annotations

from dataclasses import dataclass
import json
import os
from pathlib import Path
from typing import Any

CURRENT_PROVIDER_TERMS_VERSION = "2.1"

EEA_COUNTRY_CODES = frozenset({
    "AT", "BE", "BG", "HR", "CY", "CZ", "DE", "DK", "EE", "ES", "FI", "FR", "GR", "HU",
    "IE", "IS", "IT", "LI", "LT", "LU", "LV", "MT", "NL", "NO", "PL", "PT", "RO", "SE",
    "SI", "SK",
})


class ProductionComplianceError(RuntimeError):
    """Raised when a production compliance prerequisite is absent or invalid."""


def production_mode() -> bool:
    return os.environ.get("COMPUTEMESH_PRODUCTION_MODE", "").strip() == "1"


def _required_flag(name: str) -> None:
    if os.environ.get(name, "").strip() != "1":
        raise ProductionComplianceError(f"production launch blocked: {name}=1 is required")


def assert_production_launch_gate() -> None:
    """Block commercial production unless the operator has completed launch controls."""
    if not production_mode():
        return
    for name in (
        "COMPUTEMESH_LEGAL_REVIEW_APPROVED",
        "COMPUTEMESH_DPA_READY",
        "COMPUTEMESH_PROVIDER_AGREEMENT_READY",
        "COMPUTEMESH_SUBPROCESSOR_REGISTER_COMPLETE",
        "COMPUTEMESH_TRANSFER_ASSESSMENT_COMPLETE",
    ):
        _required_flag(name)
    if os.environ.get("COMPUTEMESH_PAYMENT_PROVIDER", "").strip().lower() != "stripe":
        raise ProductionComplianceError(
            "production launch blocked: COMPUTEMESH_PAYMENT_PROVIDER must be 'stripe'"
        )
    path = os.environ.get("COMPUTEMESH_PROVIDER_COMPLIANCE_REGISTRY", "").strip()
    if not path:
        raise ProductionComplianceError(
            "production launch blocked: COMPUTEMESH_PROVIDER_COMPLIANCE_REGISTRY is required"
        )
    ProviderComplianceRegistry.from_path(Path(path))


@dataclass(frozen=True)
class ProviderComplianceRecord:
    node_id: str
    country_code: str
    business_verified: bool
    status: str
    provider_terms_version: str
    provider_terms_accepted: bool
    data_processing_terms_accepted: bool
    no_prompt_logging_attested: bool
    payment_processor: str


class ProviderComplianceRegistry:
    """Server-owned provider eligibility registry; provider-supplied telemetry is not trusted."""

    def __init__(self, records: dict[str, ProviderComplianceRecord]) -> None:
        self._records = records

    @classmethod
    def from_path(cls, path: Path) -> "ProviderComplianceRegistry":
        if path.is_symlink() or not path.is_file():
            raise ProductionComplianceError("provider compliance registry must be a regular file")
        try:
            document = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise ProductionComplianceError("provider compliance registry must be valid UTF-8 JSON") from exc
        if not isinstance(document, dict) or document.get("schema_version") != 1:
            raise ProductionComplianceError("provider compliance registry schema_version must be 1")
        rows = document.get("providers")
        if not isinstance(rows, list):
            raise ProductionComplianceError("provider compliance registry providers must be a list")
        records: dict[str, ProviderComplianceRecord] = {}
        for raw in rows:
            if not isinstance(raw, dict):
                raise ProductionComplianceError("provider compliance record must be an object")
            node_id = str(raw.get("node_id", "")).strip()
            if not node_id or node_id in records:
                raise ProductionComplianceError("provider compliance node_id is missing or duplicated")
            record = ProviderComplianceRecord(
                node_id=node_id,
                country_code=str(raw.get("country_code", "")).strip().upper(),
                business_verified=raw.get("business_verified") is True,
                status=str(raw.get("status", "")).strip().lower(),
                provider_terms_version=str(raw.get("provider_terms_version", "")).strip(),
                provider_terms_accepted=raw.get("provider_terms_accepted") is True,
                data_processing_terms_accepted=raw.get("data_processing_terms_accepted") is True,
                no_prompt_logging_attested=raw.get("no_prompt_logging_attested") is True,
                payment_processor=str(raw.get("payment_processor", "")).strip().lower(),
            )
            records[node_id] = record
        return cls(records)

    def require_eligible(self, node_id: str) -> ProviderComplianceRecord:
        record = self._records.get(node_id)
        if record is None:
            raise ProductionComplianceError("provider is not present in the server-owned compliance registry")
        if record.status != "active":
            raise ProductionComplianceError("provider compliance status is not active")
        if record.country_code not in EEA_COUNTRY_CODES:
            raise ProductionComplianceError("provider is outside the default EEA production pool")
        if not record.business_verified:
            raise ProductionComplianceError("provider business status is not verified")
        if record.provider_terms_version != CURRENT_PROVIDER_TERMS_VERSION or not record.provider_terms_accepted:
            raise ProductionComplianceError("current provider terms have not been accepted")
        if not record.data_processing_terms_accepted:
            raise ProductionComplianceError("provider data-processing obligations have not been accepted")
        if not record.no_prompt_logging_attested:
            raise ProductionComplianceError("provider no-prompt-logging obligation is not attested")
        if record.payment_processor not in {"stripe_connect", "none"}:
            raise ProductionComplianceError("provider payout processor is not approved")
        return record


def load_provider_compliance_registry_from_env() -> ProviderComplianceRegistry | None:
    if not production_mode():
        return None
    raw = os.environ.get("COMPUTEMESH_PROVIDER_COMPLIANCE_REGISTRY", "").strip()
    if not raw:
        raise ProductionComplianceError("production provider compliance registry is required")
    return ProviderComplianceRegistry.from_path(Path(raw))


def require_production_model_attribution(manifest: dict[str, Any]) -> None:
    """Require third-party provenance/attribution for models exposed in production."""
    if not production_mode():
        return
    upstream = manifest.get("upstream")
    if not isinstance(upstream, dict):
        raise ProductionComplianceError("production model manifest requires upstream attribution")
    for key in ("publisher", "model_name", "source"):
        if not isinstance(upstream.get(key), str) or not upstream[key].strip():
            raise ProductionComplianceError(f"production model upstream.{key} is required")
    license_record = manifest.get("license")
    if (
        not isinstance(license_record, dict)
        or not str(license_record.get("id", "")).strip()
        or not str(license_record.get("source", "")).strip()
    ):
        raise ProductionComplianceError("production model requires explicit license id and source")
