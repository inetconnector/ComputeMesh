"""ComputeMesh Public Portal Registration Routes Handler.

Handles /api/v1/register for consumers and providers with AES-256-GCM vault encryption.
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

from services.identity.vault import DEFAULT_VAULT

# In-memory customer & billing store with AES-256-GCM encrypted fields
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
    """Handles consumer and provider registration with encrypted vaults."""

    def __init__(self, store: dict[str, dict[str, Any]] | None = None) -> None:
        self.store = REGISTERED_ACCOUNTS if store is None else store

    def handle_register(self, body: dict[str, Any]) -> tuple[dict[str, Any] | None, str | None, HTTPStatus]:
        email = str(body.get("email", "")).strip().lower()
        role = str(body.get("role", "consumer")).strip().lower()
        wallet = str(body.get("wallet", "")).strip()

        if not email or "@" not in email:
            return (None, "Valid email address is required", HTTPStatus.BAD_REQUEST)

        if role not in ("consumer", "provider"):
            return (None, "role must be either consumer or provider", HTTPStatus.BAD_REQUEST)

        prefix = "cm_live_" if role == "consumer" else "cm_provider_"
        token = prefix + secrets.token_hex(16)
        account_id = f"acc_{secrets.token_hex(8)}"
        created_at = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")

        encrypted_wallet = DEFAULT_VAULT.encrypt(wallet) if wallet else None
        encrypted_email = DEFAULT_VAULT.encrypt(email)

        self.store[token] = {
            "account_id": account_id,
            "email_encrypted": encrypted_email,
            "email_masked": DEFAULT_VAULT.mask_sensitive(email),
            "role": role,
            "wallet_encrypted": encrypted_wallet,
            "wallet_masked": DEFAULT_VAULT.mask_sensitive(wallet) if wallet else None,
            "balance_micro_credits": 10000000 if role == "consumer" else 0,  # $10 free credit
            "created_at": created_at,
        }

        _persist_api_key_record(_api_key_store_path(), {
            "api_key": token,
            "account_id": account_id,
            "role": role,
            "email_masked": DEFAULT_VAULT.mask_sensitive(email),
            "created_at": created_at,
        })

        return ({
            "status": "success",
            "account_id": account_id,
            "api_key": token,
            "role": role,
            "payout_target_masked": DEFAULT_VAULT.mask_sensitive(wallet) if wallet else None,
            "encryption": "AES-256-GCM",
            "free_credit_granted_usd": 10.0 if role == "consumer" else 0.0,
        }, None, HTTPStatus.CREATED)
