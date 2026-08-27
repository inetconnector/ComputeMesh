"""ComputeMesh public portal registration routes.

Credential issuance is fail-closed for B2B contract incorporation. Provider accounts
have additional EEA, confidentiality/data-processing and no-prompt-logging
requirements. Account registration alone never makes a provider node schedulable;
production node eligibility is controlled by the server-owned provider registry.
"""
from __future__ import annotations

from datetime import datetime, timezone
from http import HTTPStatus
import json
import os
from pathlib import Path
import secrets
import sys
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from services.compliance.policy import EEA_COUNTRY_CODES
from services.identity.vault import DEFAULT_VAULT

CURRENT_TERMS_VERSION = "2.1"
REGISTERED_ACCOUNTS: dict[str, dict[str, Any]] = {}


def _api_key_store_path() -> Path | None:
    raw = os.environ.get("COMPUTEMESH_API_KEY_STORE_PATH", "").strip()
    return Path(raw) if raw else None


def _persist_api_key_record(path: Path | None, record: dict[str, Any]) -> None:
    if path is None:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    records: list[dict[str, Any]] = []
    if path.exists():
        try:
            raw = path.read_text(encoding="utf-8").strip()
            if raw:
                parsed = json.loads(raw)
                if isinstance(parsed, dict) and isinstance(parsed.get("keys"), list):
                    records = [r for r in parsed["keys"] if isinstance(r, dict)]
                elif isinstance(parsed, list):
                    records = [r for r in parsed if isinstance(r, dict)]
        except json.JSONDecodeError:
            for line in path.read_text(encoding="utf-8").splitlines():
                try:
                    item = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if isinstance(item, dict):
                    records.append(item)
    records = [r for r in records if r.get("api_key") != record["api_key"]]
    records.append(record)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps({"keys": records}, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    tmp.replace(path)


class PortalRegistrationHandler:
    """Handle B2B consumer/provider registration with auditable clickwrap acceptance."""

    def __init__(self, store: dict[str, dict[str, Any]] | None = None) -> None:
        self.store = REGISTERED_ACCOUNTS if store is None else store

    def handle_register(self, body: dict[str, Any]) -> tuple[dict[str, Any] | None, str | None, HTTPStatus]:
        email = str(body.get("email", "")).strip().lower()
        role = str(body.get("role", "consumer")).strip().lower()
        wallet = str(body.get("wallet", "")).strip()
        country_code = str(body.get("country_code", "")).strip().upper()
        terms_version = str(body.get("terms_version", "")).strip()
        accepted_terms = body.get("accepted_terms") is True
        privacy_acknowledged = body.get("privacy_acknowledged") is True
        business_user = body.get("business_user") is True
        provider_data_terms = body.get("provider_data_processing_terms_accepted") is True
        no_prompt_logging = body.get("no_prompt_logging_attested") is True

        if not email or "@" not in email:
            return (None, "Valid email address is required", HTTPStatus.BAD_REQUEST)
        if role not in ("consumer", "provider"):
            return (None, "role must be either consumer or provider", HTTPStatus.BAD_REQUEST)
        if terms_version != CURRENT_TERMS_VERSION or not accepted_terms:
            return (None, f"Acceptance of Terms version {CURRENT_TERMS_VERSION} is required", HTTPStatus.BAD_REQUEST)
        if not privacy_acknowledged:
            return (None, "Privacy notice acknowledgement is required", HTTPStatus.BAD_REQUEST)
        if not business_user:
            return (None, "ComputeMesh account registration is currently restricted to business users", HTTPStatus.FORBIDDEN)
        if role == "provider":
            if country_code not in EEA_COUNTRY_CODES:
                return (None, "Production provider registration is currently restricted to EEA countries", HTTPStatus.FORBIDDEN)
            if not provider_data_terms:
                return (None, "Provider confidentiality/data-processing obligations must be accepted", HTTPStatus.BAD_REQUEST)
            if not no_prompt_logging:
                return (None, "Provider no-prompt-logging obligation must be accepted", HTTPStatus.BAD_REQUEST)

        prefix = "cm_live_" if role == "consumer" else "cm_provider_"
        token = prefix + secrets.token_hex(16)
        account_id = f"acc_{secrets.token_hex(8)}"
        created_at = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
        encrypted_wallet = DEFAULT_VAULT.encrypt(wallet) if wallet else None
        encrypted_email = DEFAULT_VAULT.encrypt(email)

        record = {
            "account_id": account_id,
            "email_encrypted": encrypted_email,
            "email_masked": DEFAULT_VAULT.mask_sensitive(email),
            "role": role,
            "wallet_encrypted": encrypted_wallet,
            "wallet_masked": DEFAULT_VAULT.mask_sensitive(wallet) if wallet else None,
            "country_code": country_code if role == "provider" else None,
            "balance_micro_credits": 10000000 if role == "consumer" else 0,
            "created_at": created_at,
            "terms_version": CURRENT_TERMS_VERSION,
            "terms_accepted_at": created_at,
            "privacy_acknowledged_at": created_at,
            "business_user_confirmed": True,
            "provider_data_processing_terms_accepted_at": created_at if role == "provider" else None,
            "no_prompt_logging_attested_at": created_at if role == "provider" else None,
            "production_node_eligible": False,
        }
        self.store[token] = record

        _persist_api_key_record(
            _api_key_store_path(),
            {
                "api_key": token,
                "account_id": account_id,
                "role": role,
                "email_masked": DEFAULT_VAULT.mask_sensitive(email),
                "country_code": country_code if role == "provider" else None,
                "created_at": created_at,
                "terms_version": CURRENT_TERMS_VERSION,
                "terms_accepted_at": created_at,
                "privacy_acknowledged_at": created_at,
                "business_user_confirmed": True,
                "provider_data_processing_terms_accepted_at": created_at if role == "provider" else None,
                "no_prompt_logging_attested_at": created_at if role == "provider" else None,
                "production_node_eligible": False,
            },
        )

        return (
            {
                "status": "success",
                "account_id": account_id,
                "api_key": token,
                "role": role,
                "payout_target_masked": DEFAULT_VAULT.mask_sensitive(wallet) if wallet else None,
                "encryption": "AES-256-GCM",
                "free_credit_granted_usd": 10.0 if role == "consumer" else 0.0,
                "terms_version": CURRENT_TERMS_VERSION,
                "terms_accepted_at": created_at,
                "production_node_eligible": False if role == "provider" else None,
            },
            None,
            HTTPStatus.CREATED,
        )
