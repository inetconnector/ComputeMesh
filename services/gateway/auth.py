from __future__ import annotations

from dataclasses import dataclass
import hashlib
import hmac
from http import HTTPStatus
import json
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
from services.billing.owner_accounts import OwnerAccountStore
from services.billing.owner_credits import OwnerCreditLedger
from services.common.config import CONFIG
from services.gateway.teaser import TeaserQuotaManager

PROVIDER_NODE_ID_REGEX = re.compile(r"^[a-zA-Z0-9_\-\.]{3,64}$")
API_KEY_REGEX = re.compile(r"^[a-zA-Z0-9_\-\.]{8,128}$")
ADMIN_KEY_MIN_LENGTH = 24


def _env_truthy(name: str) -> bool:
    return os.environ.get(name, "").strip().lower() in ("1", "true", "yes", "on")


def api_credential_id(token: str) -> str:
    """Return a non-secret durable identifier for an API credential.

    The owner store must never need the raw bearer token. A SHA-256 identifier is
    sufficient to bind/revoke a credential without making the billing database a
    second API-key secret store.
    """
    if not token:
        raise ValueError("API token is required")
    return "api_sha256:" + hashlib.sha256(token.encode("utf-8")).hexdigest()


def _load_env_api_keys() -> dict[str, str]:
    """Load static API keys from COMPUTEMESH_API_KEYS as token:account_id pairs."""
    configured = os.environ.get("COMPUTEMESH_API_KEYS", "").strip()
    if not configured:
        return {}
    result: dict[str, str] = {}
    for raw_entry in configured.split(","):
        entry = raw_entry.strip()
        if not entry:
            continue
        sep = ":" if ":" in entry else "="
        if sep not in entry:
            continue
        token, account_id = entry.split(sep, 1)
        token = token.strip()
        account_id = account_id.strip()
        if token and account_id and API_KEY_REGEX.match(token):
            result[token] = account_id
    return result


def _load_api_key_store(path: Path | None) -> dict[str, str]:
    """Load JSON or JSONL token/account records from the shared portal/gateway store."""
    if path is None or not path.exists():
        return {}
    try:
        raw = path.read_text(encoding="utf-8").strip()
    except Exception:
        return {}
    if not raw:
        return {}

    records: list[dict[str, Any]] = []
    try:
        parsed = json.loads(raw)
        if isinstance(parsed, dict):
            if isinstance(parsed.get("keys"), list):
                records = [r for r in parsed["keys"] if isinstance(r, dict)]
            else:
                records = [parsed]
        elif isinstance(parsed, list):
            records = [r for r in parsed if isinstance(r, dict)]
    except json.JSONDecodeError:
        for line in raw.splitlines():
            try:
                item = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(item, dict):
                records.append(item)

    result: dict[str, str] = {}
    for record in records:
        token = str(record.get("api_key") or record.get("token") or "").strip()
        account_id = str(record.get("account_id") or "").strip()
        if token and account_id and API_KEY_REGEX.match(token):
            result[token] = account_id
    return result


@dataclass(frozen=True)
class AuthResult:
    account_id: str | None = None
    owner_id: str | None = None
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


TRUSTED_PROXIES: set[str] = {"127.0.0.1", "::1", "localhost"}


def resolve_client_ip(
    headers: Any,
    client_address: tuple[str, int] | None = None,
    trusted_proxies: set[str] | None = None,
) -> str:
    peer_ip = str(client_address[0]) if client_address and len(client_address) > 0 else "127.0.0.1"
    trusted = trusted_proxies if trusted_proxies is not None else TRUSTED_PROXIES
    is_trusted_peer = peer_ip in trusted or peer_ip.startswith("127.") or peer_ip == "::1"
    if headers and is_trusted_peer:
        forwarded = str(headers.get("X-Forwarded-For", "")).strip()
        if forwarded:
            ip = forwarded.split(",")[0].strip()
            if ip and len(ip) <= 45:  # IPv6 max length
                return ip
        real_ip = str(headers.get("X-Real-IP", "")).strip()
        if real_ip and len(real_ip) <= 45:
            return real_ip
    return peer_ip


class GatewayAuthManager:
    """Manages API keys, customer accounts, and caller entitlement tiers with constant-time security."""

    def __init__(
        self,
        ledger: Ledger,
        teaser_manager: TeaserQuotaManager,
        api_keys: dict[str, str] | None = None,
        api_key_store_path: Path | None = None,
        owner_account_store: OwnerAccountStore | None = None,
    ) -> None:
        self.ledger = ledger
        self.teaser_manager = teaser_manager
        self.owner_account_store = owner_account_store
        self._initial_api_keys: dict[str, str] = api_keys.copy() if api_keys is not None else {}
        self._explicit_keys: dict[str, str] = {}
        self._api_keys: dict[str, str] = {}
        store_path = api_key_store_path or (
            Path(os.environ["COMPUTEMESH_API_KEY_STORE_PATH"])
            if os.environ.get("COMPUTEMESH_API_KEY_STORE_PATH")
            else None
        )
        self.api_key_store_path = store_path
        self._lock = threading.RLock()
        self.refresh_registered_keys()

    @property
    def api_keys(self) -> dict[str, str]:
        return self._api_keys

    @property
    def uses_owner_credits(self) -> bool:
        return isinstance(self.ledger, OwnerCreditLedger)

    def _bind_owner_credential(self, token: str, owner_id: str) -> None:
        if self.owner_account_store is None:
            if self.uses_owner_credits:
                raise RuntimeError("unified owner credits require OwnerAccountStore")
            return
        self.owner_account_store.ensure_owner(owner_id)
        self.owner_account_store.bind_api_credential(owner_id, api_credential_id(token))

    def set_api_key(self, token: str, account_id: str) -> None:
        if not API_KEY_REGEX.match(token):
            raise ValueError("invalid API key format")
        if not account_id.strip():
            raise ValueError("account_id is required")
        with self._lock:
            self._explicit_keys[token] = account_id.strip()
            self._api_keys[token] = account_id.strip()
        if self.uses_owner_credits:
            self._bind_owner_credential(token, account_id.strip())

    def refresh_registered_keys(self) -> None:
        with self._lock:
            fresh_keys = self._initial_api_keys.copy()
            fresh_keys.update(_load_env_api_keys())
            fresh_keys.update(_load_api_key_store(self.api_key_store_path))
            fresh_keys.update(self._explicit_keys)
            self._api_keys = fresh_keys

    def _lookup_registered_key(self, token: str) -> str | None:
        self.refresh_registered_keys()
        with self._lock:
            for registered_token, account_id in self._api_keys.items():
                if hmac.compare_digest(token, registered_token):
                    return account_id
        return None

    def is_valid_key(self, token: str) -> bool:
        """Verifies whether a token is a valid registered API key using constant-time comparison."""
        if not token or not isinstance(token, str):
            return False
        return self._lookup_registered_key(token) is not None

    def authenticate_request(
        self,
        headers: Any,
        client_address: tuple[str, int] | None = None,
        allow_teaser: bool = False,
    ) -> AuthResult:
        token = extract_bearer_token(headers)

        if token:
            # Check registered keys using constant-time comparison. In unified mode,
            # the configured account_id is the durable owner_id. No automatic
            # production credit is created merely by presenting a key.
            account_id = self._lookup_registered_key(token)
            if account_id:
                if self.uses_owner_credits:
                    self._bind_owner_credential(token, account_id)
                    return AuthResult(
                        account_id=account_id,
                        owner_id=account_id,
                        is_teaser=False,
                        is_provider_self_compute=token.startswith("cm_provider_"),
                        is_quota_exceeded=False,
                    )

                if not self.ledger.has_received_initial_grant(account_id) and self.ledger.get_balance(account_id) == 0:
                    self.ledger.deposit_customer_credits(
                        customer_account_id=account_id,
                        amount_micro_units=10_000_000,
                        payment_reference=f"initial_grant_{account_id}",
                    )
                return AuthResult(
                    account_id=account_id,
                    is_teaser=False,
                    is_provider_self_compute=token.startswith("cm_provider_"),
                    is_quota_exceeded=False,
                )

            # Lab/private appliance compatibility must be enabled explicitly.
            if token.startswith("cm_provider_") and _env_truthy("COMPUTEMESH_ALLOW_DYNAMIC_PROVIDER_TOKENS"):
                provider_node_id = token.removeprefix("cm_provider_").strip()
                if PROVIDER_NODE_ID_REGEX.match(provider_node_id):
                    account_id = f"provider_self_{provider_node_id}"
                    with self._lock:
                        self._api_keys[token] = account_id
                    if self.uses_owner_credits:
                        self._bind_owner_credential(token, account_id)
                        return AuthResult(
                            account_id=account_id,
                            owner_id=account_id,
                            is_teaser=False,
                            is_provider_self_compute=True,
                            is_quota_exceeded=False,
                        )
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

            if token.startswith("cm_live_") and _env_truthy("COMPUTEMESH_ALLOW_DYNAMIC_CUSTOMER_KEYS"):
                cust_suffix = token.removeprefix("cm_live_").strip()
                if API_KEY_REGEX.match(token):
                    account_id = f"cust_{cust_suffix}"
                    with self._lock:
                        self._api_keys[token] = account_id
                    if self.uses_owner_credits:
                        self._bind_owner_credential(token, account_id)
                        return AuthResult(
                            account_id=account_id,
                            owner_id=account_id,
                            is_teaser=False,
                            is_provider_self_compute=False,
                            is_quota_exceeded=False,
                        )
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

        # No token provided: evaluate Free Teaser Playground Mode. Teaser quota is
        # deliberately separate from durable owner balances and remains legacy/demo
        # accounting even when owner credits are enabled.
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
                if self._lookup_registered_key(token) or _env_truthy("COMPUTEMESH_ALLOW_DYNAMIC_PROVIDER_TOKENS"):
                    return (node_id, None, HTTPStatus.OK)
                return (None, "Provider token is not registered", HTTPStatus.UNAUTHORIZED)
            return (None, "Invalid provider node ID format in token", HTTPStatus.BAD_REQUEST)
        return (None, "Invalid provider authorization token format", HTTPStatus.UNAUTHORIZED)

    def authenticate_admin(self, headers: Any) -> tuple[bool, str | None, HTTPStatus]:
        token = extract_bearer_token(headers)
        if not token:
            return (False, "Missing Authorization header for admin endpoint", HTTPStatus.UNAUTHORIZED)
        env_admin = os.environ.get("COMPUTEMESH_ADMIN_KEY", "").strip()
        if len(env_admin) < ADMIN_KEY_MIN_LENGTH:
            return (False, "Admin key is not configured", HTTPStatus.SERVICE_UNAVAILABLE)
        if hmac.compare_digest(token, env_admin):
            return (True, None, HTTPStatus.OK)
        return (False, "Invalid admin credentials", HTTPStatus.FORBIDDEN)
