"""Internal bridge between the private promo policy service and public owner ledger.

The bridge exposes only two reduced operations to an authenticated internal caller:
- read the minimum owner state needed for private promo policy;
- apply a short-lived Ed25519-signed promo grant decision.

It never accepts an unsigned grant amount and never exposes raw hardware evidence.
"""
from __future__ import annotations

import base64
import binascii
import hmac
import json
import os
from dataclasses import asdict, dataclass
from typing import Any, Mapping

from services.billing.owner_accounts import OwnerAccountStore
from services.billing.owner_credits import OwnerCreditLedger
from services.billing.signed_promo_grants import (
    DEVICE_CLAIM,
    GPU_CLAIM,
    PromoDecisionVerifier,
    PromoGrantDecisionError,
    SignedPromoGrantApplier,
)

MIN_INTERNAL_TOKEN_LENGTH = 24
MAX_TRUSTED_PROMO_KEYS = 16


class PromoInternalError(ValueError):
    """Invalid internal promo request or configuration."""


@dataclass(frozen=True)
class PromoEligibilityView:
    owner_id: str
    current_owner_promo_micro_units: int
    already_claimed_classes: tuple[str, ...]
    provider_node_owner_id: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _decode_public_key(value: str) -> bytes:
    text = str(value or "").strip()
    if not text or len(text) > 128:
        raise PromoInternalError("invalid promo decision public key")
    if any(ch not in "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_" for ch in text):
        raise PromoInternalError("invalid promo decision public key encoding")
    padded = text + "=" * ((4 - len(text) % 4) % 4)
    try:
        raw = base64.urlsafe_b64decode(padded.encode("ascii"))
    except (ValueError, binascii.Error) as exc:
        raise PromoInternalError("invalid promo decision public key encoding") from exc
    if len(raw) != 32:
        raise PromoInternalError("promo decision public key must contain 32 raw bytes")
    return raw


def load_trusted_promo_keys(configured_json: str) -> dict[str, bytes]:
    """Parse a bounded JSON object of key-id -> raw Ed25519 public-key base64url."""
    try:
        value = json.loads(configured_json)
    except json.JSONDecodeError as exc:
        raise PromoInternalError("promo decision public key configuration is not valid JSON") from exc
    if not isinstance(value, dict) or not value or len(value) > MAX_TRUSTED_PROMO_KEYS:
        raise PromoInternalError("promo decision public key configuration must be a bounded object")
    result: dict[str, bytes] = {}
    for raw_key_id, encoded_key in value.items():
        key_id = str(raw_key_id or "").strip()
        if not key_id or len(key_id) > 128 or key_id in result:
            raise PromoInternalError("invalid promo decision key id")
        result[key_id] = _decode_public_key(str(encoded_key or ""))
    return result


class PromoInternalService:
    """Authenticated minimal state/read + signed grant/apply bridge."""

    def __init__(
        self,
        *,
        owner_store: OwnerAccountStore,
        ledger: OwnerCreditLedger,
        trusted_keys: Mapping[str, bytes],
        bearer_token: str,
    ) -> None:
        token = str(bearer_token or "").strip()
        if len(token) < MIN_INTERNAL_TOKEN_LENGTH:
            raise ValueError("promo internal bearer token is too short")
        self.owner_store = owner_store
        self.ledger = ledger
        self._bearer_token = token
        self.verifier = PromoDecisionVerifier(trusted_keys)
        self.applier = SignedPromoGrantApplier(
            owner_store=owner_store,
            ledger=ledger,
            verifier=self.verifier,
        )

    def authenticate(self, authorization: str) -> bool:
        prefix = "Bearer "
        value = str(authorization or "")
        if not value.startswith(prefix):
            return False
        return hmac.compare_digest(value[len(prefix) :], self._bearer_token)

    def eligibility(self, body: Mapping[str, Any]) -> PromoEligibilityView:
        allowed = {"owner_id", "node_id"}
        if not isinstance(body, Mapping) or not set(body) <= allowed or "owner_id" not in body:
            raise PromoInternalError("invalid promo eligibility contract")
        owner_id = str(body.get("owner_id") or "").strip()
        node_id = str(body.get("node_id") or "").strip()
        if not owner_id or len(owner_id) > 256 or len(node_id) > 128:
            raise PromoInternalError("invalid promo eligibility subject")
        if self.owner_store.get_owner(owner_id) is None:
            raise PromoInternalError("unknown owner")

        claimed = tuple(
            claim_class
            for claim_class in (DEVICE_CLAIM, GPU_CLAIM)
            if self.owner_store.promo_claim_for_owner(owner_id, claim_class) is not None
        )
        provider_owner = self.owner_store.owner_for_provider_node(node_id) if node_id else None
        return PromoEligibilityView(
            owner_id=owner_id,
            current_owner_promo_micro_units=self.ledger.get_owner_balances(
                owner_id
            ).promo_micro_units,
            already_claimed_classes=claimed,
            provider_node_owner_id=provider_owner or "",
        )

    def apply(self, body: Mapping[str, Any], *, now: float | None = None) -> dict[str, Any]:
        try:
            result = self.applier.apply(body, now=now)
        except PromoGrantDecisionError as exc:
            raise PromoInternalError(str(exc)) from exc
        return {
            "owner_id": result.owner_id,
            "claim_id": result.claim_id,
            "claim_class": result.claim_class,
            "amount_micro_units": result.amount_micro_units,
            "policy_version": result.policy_version,
            "ledger_status": result.ledger_status,
        }


def build_promo_internal_service_from_env(
    *,
    owner_store: OwnerAccountStore,
    ledger: OwnerCreditLedger,
) -> PromoInternalService | None:
    """Build the bridge only when both auth and trusted-key configuration exist."""
    token = os.environ.get("COMPUTEMESH_PROMO_INTERNAL_TOKEN", "").strip()
    keys_json = os.environ.get("COMPUTEMESH_PROMO_DECISION_PUBLIC_KEYS_JSON", "").strip()
    if not token and not keys_json:
        return None
    if not token or not keys_json:
        raise RuntimeError(
            "promo internal bridge requires both COMPUTEMESH_PROMO_INTERNAL_TOKEN and "
            "COMPUTEMESH_PROMO_DECISION_PUBLIC_KEYS_JSON"
        )
    try:
        trusted_keys = load_trusted_promo_keys(keys_json)
        return PromoInternalService(
            owner_store=owner_store,
            ledger=ledger,
            trusted_keys=trusted_keys,
            bearer_token=token,
        )
    except (PromoInternalError, ValueError) as exc:
        raise RuntimeError(f"invalid promo internal bridge configuration: {exc}") from exc
