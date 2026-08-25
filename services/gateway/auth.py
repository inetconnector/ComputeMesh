from __future__ import annotations

from dataclasses import dataclass
import hmac
from http import HTTPStatus
import os
from pathlib import Path
import re
import secrets
import sys
import threading
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from services.billing.ledger import Ledger
from services.common.config import CONFIG
from services.gateway.teaser import TeaserQuotaManager

PROVIDER_NODE_ID_REGEX = re.compile(r"^[a-zA-Z0-9_\-\.]{3,64}$")
API_KEY_REGEX = re.compile(r"^[a-zA-Z0-9_\-\.]{8,128}$")


@dataclass(frozen=True)
class AuthResult:
    account_id: str | None = None
    is_teaser: bool = False
    is_provider_self_compute: bool = False
    is_quota_exceeded: bool = False
    error_message: str | None = None
    status_code: HTTPStatus = HTTPStatus.OK

    @property
    def is_authenticated(self) -> bool:
        return self.account_id is not None or (self.is_teaser and self.is_quota_exceeded)


def extract_bearer_token(headers: Any) -> str:
    auth_header = str(headers.get("Authorization", "")).strip() if headers else ""
    if auth_header.startswith("Bearer "):
        return auth_header.removeprefix("Bearer ").strip()
    return ""


def resolve_client_ip(headers: Any, client_address: tuple[str, int] | None = None) -> str:
    if headers:
        forwarded = str(headers.get("X-Forwarded-For", "")).strip()
        if forwarded:
            ip = forwarded.split(",")[0].strip()
            if ip and len(ip) <= 45:  # IPv6 max length
                return ip
        real_ip = str(headers.get("X-Real-IP", "")).strip()
        if real_ip and len(real_ip) <= 45:
            return real_ip
    if client_address and len(client_address) > 0:
        return str(client_address[0])
    return "127.0.0.1"


class GatewayAuthManager:
    """Manages API keys, customer accounts, and caller entitlement tiers with constant-time security."""

    def __init__(
        self,
        ledger: Ledger,
        teaser_manager: TeaserQuotaManager,
        api_keys: dict[str, str] | None = None,
    ) -> None:
        self.ledger = ledger
        self.teaser_manager = teaser_manager
        self._api_keys: dict[str, str] = api_keys if api_keys is not None else {}
        self._lock = threading.RLock()

    @property
    def api_keys(self) -> dict[str, str]:
        return self._api_keys

    def set_api_key(self, token: str, account_id: str) -> None:
        with self._lock:
            self._api_keys[token] = account_id

    def authenticate_request(
        self,
        headers: Any,
        client_address: tuple[str, int] | None = None,
        allow_teaser: bool = False,
    ) -> AuthResult:
        token = extract_bearer_token(headers)

        if token:
            # Check registered keys using constant-time comparison
            with self._lock:
                for registered_token, account_id in self._api_keys.items():
                    if hmac.compare_digest(token, registered_token):
                        if self.ledger.get_balance(account_id) == 0:
                            self.ledger.deposit_customer_credits(
                                customer_account_id=account_id,
                                amount_micro_units=10_000_000,
                                payment_reference=f"initial_grant_{account_id}_{secrets.token_hex(4)}",
                            )
                        return AuthResult(
                            account_id=account_id,
                            is_teaser=False,
                            is_provider_self_compute=token.startswith("cm_provider_"),
                            is_quota_exceeded=False,
                        )

            # 1. Provider self-compute token (0% platform markup)
            if token.startswith("cm_provider_"):
                provider_node_id = token.removeprefix("cm_provider_").strip()
                if PROVIDER_NODE_ID_REGEX.match(provider_node_id):
                    account_id = f"provider_self_{provider_node_id}"
                    with self._lock:
                        self._api_keys[token] = account_id
                    if self.ledger.get_balance(account_id) == 0:
                        self.ledger.deposit_customer_credits(
                            customer_account_id=account_id,
                            amount_micro_units=100_000_000,
                            payment_reference=f"provider_self_grant_{account_id}_{secrets.token_hex(4)}",
                        )
                    return AuthResult(
                        account_id=account_id,
                        is_teaser=False,
                        is_provider_self_compute=True,
                        is_quota_exceeded=False,
                    )

            # 2. Registered live customer token
            if token.startswith("cm_live_"):
                cust_suffix = token.removeprefix("cm_live_").strip()
                if API_KEY_REGEX.match(token):
                    account_id = f"cust_{cust_suffix}"
                    with self._lock:
                        self._api_keys[token] = account_id
                    if self.ledger.get_balance(account_id) == 0:
                        self.ledger.deposit_customer_credits(
                            customer_account_id=account_id,
                            amount_micro_units=10_000_000,
                            payment_reference=f"initial_grant_{account_id}_{secrets.token_hex(4)}",
                        )
                    return AuthResult(
                        account_id=account_id,
                        is_teaser=False,
                        is_provider_self_compute=False,
                        is_quota_exceeded=False,
                    )

        # 3. No token provided: evaluate Free Teaser Playground Mode
        if allow_teaser:
            client_ip = resolve_client_ip(headers, client_address)
            session = self.teaser_manager.get_or_create_session(client_ip)
            if session.is_quota_exceeded:
                return AuthResult(
                    account_id=None,
                    is_teaser=True,
                    is_provider_self_compute=False,
                    is_quota_exceeded=True,
                )

            # Auto-provision temporary teaser ledger balance
            sanitized_ip = re.sub(r"[^a-zA-Z0-9_]", "_", client_ip)
            account_id = f"teaser_{sanitized_ip}"
            if self.ledger.get_balance(account_id) == 0:
                self.ledger.deposit_customer_credits(
                    customer_account_id=account_id,
                    amount_micro_units=CONFIG.teaser.initial_grant_micro_units,
                    payment_reference=f"teaser_grant_{account_id}_{secrets.token_hex(4)}",
                )
            return AuthResult(
                account_id=account_id,
                is_teaser=True,
                is_provider_self_compute=False,
                is_quota_exceeded=False,
            )

        return AuthResult(
            account_id=None,
            is_teaser=False,
            is_provider_self_compute=False,
            is_quota_exceeded=False,
            error_message="Missing or invalid Authorization header. Expected 'Bearer <api_key>'",
            status_code=HTTPStatus.UNAUTHORIZED,
        )

    def authenticate_provider(self, headers: Any) -> tuple[str | None, str | None, HTTPStatus]:
        token = extract_bearer_token(headers)
        if not token:
            return (None, "Missing provider authorization token", HTTPStatus.UNAUTHORIZED)
        if token.startswith("cm_provider_"):
            node_id = token.removeprefix("cm_provider_").strip()
            if PROVIDER_NODE_ID_REGEX.match(node_id):
                return (node_id, None, HTTPStatus.OK)
            return (None, "Invalid provider node ID format in token", HTTPStatus.BAD_REQUEST)
        return (None, "Invalid provider authorization token format", HTTPStatus.UNAUTHORIZED)

    def authenticate_admin(self, headers: Any) -> tuple[bool, str | None, HTTPStatus]:
        token = extract_bearer_token(headers)
        if not token:
            return (False, "Missing Authorization header for admin endpoint", HTTPStatus.UNAUTHORIZED)
        env_admin = os.environ.get("COMPUTEMESH_ADMIN_KEY", "cm_admin_master_dani_2026")
        # Constant-time comparison against configured admin secret
        if hmac.compare_digest(token, env_admin):
            return (True, None, HTTPStatus.OK)
        return (False, "Invalid admin credentials", HTTPStatus.FORBIDDEN)
