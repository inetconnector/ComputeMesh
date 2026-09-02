"""Owner-authenticated gateway bridge for hardware-bound onboarding promo.

The generic challenge/proof flow remains for device onboarding. When server-driven
GPU onboarding is enabled, GPU work must use the dedicated authenticated provider
session route; client-supplied GPU challenges/proofs are rejected at this boundary.
"""
from __future__ import annotations

import base64
import binascii
import json
import os
from http import HTTPStatus
from typing import Any

from services.billing.owner_accounts import PROMO_DEVICE, PROMO_GPU, OwnerAccountStore
from services.billing.owner_credits import OwnerCreditLedger
from services.billing.promo_recovery import reconcile_existing_promo_claim
from services.billing.signed_promo_grants import (
    PromoDecisionVerifier,
    PromoGrantDecisionError,
    SignedPromoGrantApplier,
)
from services.gateway.auth import GatewayAuthManager
from services.gateway.promo_control_plane import (
    PromoControlPlaneClient,
    PromoControlPlaneError,
)

_CHALLENGE_REQUEST_FIELDS = {"claim_class", "node_id", "key_id", "hardware_evidence"}
_CHALLENGE_RESPONSE_FIELDS = {
    "challenge_id",
    "claim_class",
    "owner_id",
    "node_id",
    "key_id",
    "hardware_claim_id",
    "evidence_digest",
    "nonce",
    "issued_at",
    "expires_at",
}
_PROOF_FIELDS = {
    "challenge_id",
    "claim_class",
    "owner_id",
    "node_id",
    "key_id",
    "hardware_claim_id",
    "evidence_digest",
    "nonce",
    "assurance_tier",
    "public_key_b64u",
    "signature_b64u",
    "accelerator_id",
    "runtime_backend",
    "runtime_build",
    "work_digest",
    "elapsed_ms",
}
_ALLOWED_CLAIMS = {PROMO_DEVICE, PROMO_GPU}


class OwnerPromoRouteError(ValueError):
    """Invalid local onboarding state or operator promo configuration."""


def _server_driven_gpu_enabled() -> bool:
    return os.environ.get("COMPUTEMESH_OWNER_PROMO_GPU_SERVER_DRIVEN", "").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }


def _b64u_key(value: str) -> bytes:
    text = str(value or "").strip()
    if not text or any(
        char not in "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_"
        for char in text
    ):
        raise OwnerPromoRouteError("invalid promo decision public key encoding")
    padded = text + "=" * ((4 - len(text) % 4) % 4)
    try:
        raw = base64.urlsafe_b64decode(padded.encode("ascii"))
    except (ValueError, UnicodeError, binascii.Error) as exc:
        raise OwnerPromoRouteError("invalid promo decision public key encoding") from exc
    if len(raw) != 32:
        raise OwnerPromoRouteError("promo decision public key must be 32 raw bytes")
    return raw


def load_trusted_promo_decision_keys_from_env() -> dict[str, bytes]:
    """Load one or more trusted private-control-plane decision keys for rotation."""
    configured = os.environ.get("COMPUTEMESH_PROMO_DECISION_TRUSTED_KEYS_JSON", "").strip()
    if configured:
        try:
            value = json.loads(configured)
        except json.JSONDecodeError as exc:
            raise OwnerPromoRouteError(
                "COMPUTEMESH_PROMO_DECISION_TRUSTED_KEYS_JSON is invalid JSON"
            ) from exc
        if not isinstance(value, dict) or not value:
            raise OwnerPromoRouteError("trusted promo decision keys must be a non-empty object")
        result: dict[str, bytes] = {}
        for key_id, encoded in value.items():
            kid = str(key_id or "").strip()
            if not kid or len(kid) > 128 or not isinstance(encoded, str):
                raise OwnerPromoRouteError("invalid trusted promo decision key entry")
            result[kid] = _b64u_key(encoded)
        return result

    key_id = os.environ.get("COMPUTEMESH_PROMO_DECISION_KEY_ID", "").strip()
    encoded = os.environ.get("COMPUTEMESH_PROMO_DECISION_PUBLIC_KEY_B64U", "").strip()
    if not key_id or not encoded:
        raise OwnerPromoRouteError(
            "trusted promo decision key configuration is required"
        )
    return {key_id: _b64u_key(encoded)}


def build_signed_promo_applier_from_env(
    *,
    owner_store: OwnerAccountStore,
    ledger: OwnerCreditLedger,
) -> SignedPromoGrantApplier:
    return SignedPromoGrantApplier(
        owner_store=owner_store,
        ledger=ledger,
        verifier=PromoDecisionVerifier(load_trusted_promo_decision_keys_from_env()),
    )


class UnifiedOwnerPromoRoutes:
    """Bridge owner-authenticated onboarding calls to the private promo service."""

    def __init__(
        self,
        *,
        owner_store: OwnerAccountStore,
        ledger: OwnerCreditLedger,
        auth_manager: GatewayAuthManager,
        control_plane: PromoControlPlaneClient,
        applier: SignedPromoGrantApplier,
    ) -> None:
        self.owner_store = owner_store
        self.ledger = ledger
        self.auth_manager = auth_manager
        self.control_plane = control_plane
        self.applier = applier

    def _owner(self, headers: Any) -> tuple[str | None, str | None, HTTPStatus]:
        auth = self.auth_manager.authenticate_request(headers, allow_teaser=False)
        owner_id = auth.owner_id or auth.account_id
        if not owner_id:
            return (
                None,
                auth.error_message or "Authenticated owner account is required",
                auth.status_code,
            )
        return (owner_id, None, HTTPStatus.OK)

    def _lifetime_claim_state(self, owner_id: str) -> tuple[list[str], int]:
        claimed: list[str] = []
        lifetime = 0
        for claim_class in (PROMO_DEVICE, PROMO_GPU):
            claim = self.owner_store.promo_claim_for_owner(owner_id, claim_class)
            if claim is not None:
                claimed.append(claim_class)
                lifetime += int(claim.amount_micro_units)
        return claimed, lifetime

    def _existing_result(self, owner_id: str, claim_class: str) -> dict[str, Any] | None:
        recovered = reconcile_existing_promo_claim(
            owner_store=self.owner_store,
            ledger=self.ledger,
            owner_id=owner_id,
            claim_class=claim_class,
        )
        if recovered is None:
            return None
        balances = self.ledger.get_owner_balances(owner_id)
        return {
            "status": "already_claimed",
            "owner_id": owner_id,
            "claim_class": claim_class,
            "amount_micro_units": recovered.amount_micro_units,
            "promo_balance_micro_units": balances.promo_micro_units,
            "ledger_status": recovered.ledger_status,
        }

    @staticmethod
    def _cp_error(exc: PromoControlPlaneError) -> tuple[str, HTTPStatus]:
        if exc.status_code == 400:
            return ("Promo verification was rejected", HTTPStatus.BAD_REQUEST)
        return ("Promo verification service is unavailable", HTTPStatus.SERVICE_UNAVAILABLE)

    def handle_challenge(
        self,
        headers: Any,
        body: dict[str, Any],
    ) -> tuple[dict[str, Any] | None, str | None, HTTPStatus]:
        owner_id, error, status = self._owner(headers)
        if owner_id is None:
            return (None, error, status)
        if set(body) != _CHALLENGE_REQUEST_FIELDS:
            return (None, "Invalid promo challenge request", HTTPStatus.BAD_REQUEST)

        claim_class = str(body.get("claim_class") or "").strip()
        node_id = str(body.get("node_id") or "").strip()
        key_id = str(body.get("key_id") or "").strip()
        evidence = body.get("hardware_evidence")
        if claim_class not in _ALLOWED_CLAIMS or not node_id or not key_id:
            return (None, "Invalid promo challenge request", HTTPStatus.BAD_REQUEST)
        if claim_class == PROMO_GPU and _server_driven_gpu_enabled():
            return (
                None,
                "GPU promo requires the server-driven provider-session endpoint",
                HTTPStatus.BAD_REQUEST,
            )
        if not isinstance(evidence, dict):
            return (None, "hardware_evidence must be an object", HTTPStatus.BAD_REQUEST)

        existing = self._existing_result(owner_id, claim_class)
        if existing is not None:
            return (existing, None, HTTPStatus.OK)

        if claim_class == PROMO_GPU:
            if self.owner_store.owner_for_provider_node(node_id) != owner_id:
                return (
                    None,
                    "GPU promo node is not owned by the authenticated owner",
                    HTTPStatus.FORBIDDEN,
                )

        try:
            challenge = self.control_plane.issue_challenge(
                {
                    "claim_class": claim_class,
                    "owner_id": owner_id,
                    "node_id": node_id,
                    "key_id": key_id,
                    "hardware_evidence": evidence,
                }
            )
        except PromoControlPlaneError as exc:
            message, cp_status = self._cp_error(exc)
            return (None, message, cp_status)

        if set(challenge) != _CHALLENGE_RESPONSE_FIELDS:
            return (None, "Invalid promo service response", HTTPStatus.BAD_GATEWAY)
        if (
            str(challenge.get("owner_id")) != owner_id
            or str(challenge.get("claim_class")) != claim_class
            or str(challenge.get("node_id")) != node_id
            or str(challenge.get("key_id")) != key_id
        ):
            return (None, "Promo service response binding mismatch", HTTPStatus.BAD_GATEWAY)
        return (challenge, None, HTTPStatus.OK)

    def handle_verify(
        self,
        headers: Any,
        body: dict[str, Any],
    ) -> tuple[dict[str, Any] | None, str | None, HTTPStatus]:
        owner_id, error, status = self._owner(headers)
        if owner_id is None:
            return (None, error, status)
        if set(body) != {"proof"} or not isinstance(body.get("proof"), dict):
            return (None, "Invalid promo verification request", HTTPStatus.BAD_REQUEST)
        proof = body["proof"]
        if set(proof) != _PROOF_FIELDS:
            return (None, "Invalid promo proof", HTTPStatus.BAD_REQUEST)

        claim_class = str(proof.get("claim_class") or "").strip()
        proof_owner = str(proof.get("owner_id") or "").strip()
        node_id = str(proof.get("node_id") or "").strip()
        if claim_class not in _ALLOWED_CLAIMS or proof_owner != owner_id or not node_id:
            return (None, "Promo proof does not match authenticated owner", HTTPStatus.FORBIDDEN)
        if claim_class == PROMO_GPU and _server_driven_gpu_enabled():
            return (
                None,
                "Client-supplied GPU promo proofs are disabled in server-driven mode",
                HTTPStatus.BAD_REQUEST,
            )

        existing = self._existing_result(owner_id, claim_class)
        if existing is not None:
            return (existing, None, HTTPStatus.OK)

        provider_owner = ""
        if claim_class == PROMO_GPU:
            provider_owner = self.owner_store.owner_for_provider_node(node_id) or ""
            if provider_owner != owner_id:
                return (
                    None,
                    "GPU promo node is not owned by the authenticated owner",
                    HTTPStatus.FORBIDDEN,
                )

        claimed_classes, lifetime_granted = self._lifetime_claim_state(owner_id)
        try:
            envelope = self.control_plane.verify_and_issue(
                {
                    "proof": proof,
                    "eligibility": {
                        "owner_id": owner_id,
                        "current_owner_promo_micro_units": lifetime_granted,
                        "already_claimed_classes": claimed_classes,
                        "provider_node_owner_id": provider_owner,
                    },
                }
            )
        except PromoControlPlaneError as exc:
            message, cp_status = self._cp_error(exc)
            return (None, message, cp_status)

        try:
            applied = self.applier.apply(envelope)
        except PromoGrantDecisionError:
            return (None, "Promo service decision was rejected", HTTPStatus.BAD_GATEWAY)

        balances = self.ledger.get_owner_balances(owner_id)
        return (
            {
                "status": "credited",
                "owner_id": owner_id,
                "claim_class": applied.claim_class,
                "amount_micro_units": applied.amount_micro_units,
                "promo_balance_micro_units": balances.promo_micro_units,
                "ledger_status": applied.ledger_status,
            },
            None,
            HTTPStatus.OK,
        )
