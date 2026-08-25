"""ComputeMesh Public Portal Registration Routes Handler.

Handles /api/v1/register for consumers and providers with AES-256-GCM vault encryption.
"""
from __future__ import annotations

from datetime import datetime, timezone
from http import HTTPStatus
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

        prefix = "cm_live_" if role == "consumer" else "cm_node_"
        token = prefix + secrets.token_hex(16)
        account_id = f"acc_{secrets.token_hex(8)}"

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
            "created_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        }

        return ({
            "status": "success",
            "account_id": account_id,
            "api_key": token,
            "role": role,
            "payout_target_masked": DEFAULT_VAULT.mask_sensitive(wallet) if wallet else None,
            "encryption": "AES-256-GCM",
            "free_credit_granted_usd": 10.0 if role == "consumer" else 0.0,
        }, None, HTTPStatus.CREATED)
