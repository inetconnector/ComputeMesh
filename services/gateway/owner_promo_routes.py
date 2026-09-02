"""Owner-authenticated gateway bridge for hardware-bound onboarding promo.

Device onboarding may use the existing challenge/proof exchange. When a trusted GPU
dispatch client is configured, GPU onboarding is server-driven end-to-end: the
gateway obtains private work inputs, dispatches them through the live authenticated
provider session, forwards only the server-observed result to private policy, and
never accepts GPU work evidence from the browser/client.
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
from services.gateway.gpu_promo_dispatch_client import (
    GpuPromoDispatchClient,
    GpuPromoDispatchClientError,
)
from services.gateway.promo_control_plane import (
    PromoControlPlaneClient,
    PromoControlPlaneError,
)

_CHALLENGE_REQUEST_FIELDS = {"claim_class", "node_id", "key_id", "hardware_evidence"}
_GPU_ONBOARD_REQUEST_FIELDS = {"node_id", "key_id", "hardware_evidence"}
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
_GPU_WORK_FIELDS = {
    "schema_version",
    "challenge_id",
    "claim_class",
    "owner_id",
    "node_id",
    "key_id",
    "hardware_claim_id",
    "evidence_digest",
    "nonce",
    "prompt",
    "seed",
    "n_predict",
    "model_sha256",
    "expected_llama_build_number",
    "expected_llama_build_commit",
    "timeout_ms",
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
_GPU_OBSERVATION_FIELDS = {"server_roundtrip_ms", "session_id", "session_revision"}
_ALLOWED_CLAIMS = {PROMO_DEVICE, PROMO_GPU}


class OwnerPromoRouteError(ValueError):
    """Invalid local onboarding state or operator promo configuration."""


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
        gpu_dispatch: GpuPromoDispatchClient | None = None,
    ) -> None:
        self.owner_store = owner_store
        self.ledger = ledger
        self.auth_manager = auth_manager
        self.control_plane = control_plane
        self.applier = applier
        self.gpu_dispatch = gpu_dispatch

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

    @staticmethod
    def _challenge_binding_ok(
        challenge: dict[str, Any],
        *,
        owner_id: str,
        claim_class: str,
        node_id: str,
        key_id: str,
    ) -> bool:
        return (
            set(challenge) == _CHALLENGE_RESPONSE_FIELDS
            and str(challenge.get("owner_id")) == owner_id
            and str(challenge.get("claim_class")) == claim_class
            and str(challenge.get("node_id")) == node_id
            and str(challenge.get("key_id")) == key_id
        )

    def _apply_envelope(
        self,
        *,
        owner_id: str,
        envelope: dict[str, Any],
    ) -> tuple[dict[str, Any] | None, str | None, HTTPStatus]:
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

    def handle_gpu_onboard(
        self,
        headers: Any,
        body: dict[str, Any],
    ) -> tuple[dict[str, Any] | None, str | None, HTTPStatus]:
        """Run the GPU promo proof entirely through trusted server-side components."""
        owner_id, error, status = self._owner(headers)
        if owner_id is None:
            return (None, error, status)
        if self.gpu_dispatch is None:
            return (None, "Server-driven GPU promo is unavailable", HTTPStatus.SERVICE_UNAVAILABLE)
        if set(body) != _GPU_ONBOARD_REQUEST_FIELDS:
            return (None, "Invalid GPU promo onboarding request", HTTPStatus.BAD_REQUEST)
        node_id = str(body.get("node_id") or "").strip()
        key_id = str(body.get("key_id") or "").strip()
        evidence = body.get("hardware_evidence")
        if not node_id or not key_id or not isinstance(evidence, dict):
            return (None, "Invalid GPU promo onboarding request", HTTPStatus.BAD_REQUEST)

        existing = self._existing_result(owner_id, PROMO_GPU)
        if existing is not None:
            return (existing, None, HTTPStatus.OK)
        if self.owner_store.owner_for_provider_node(node_id) != owner_id:
            return (
                None,
                "GPU promo node is not owned by the authenticated owner",
                HTTPStatus.FORBIDDEN,
            )

        try:
            challenge = self.control_plane.issue_challenge(
                {
                    "claim_class": PROMO_GPU,
                    "owner_id": owner_id,
                    "node_id": node_id,
                    "key_id": key_id,
                    "hardware_evidence": evidence,
                }
            )
        except PromoControlPlaneError as exc:
            message, cp_status = self._cp_error(exc)
            return (None, message, cp_status)
        if not self._challenge_binding_ok(
            challenge,
            owner_id=owner_id,
            claim_class=PROMO_GPU,
            node_id=node_id,
            key_id=key_id,
        ):
            return (None, "Promo service response binding mismatch", HTTPStatus.BAD_GATEWAY)

        try:
            work = self.control_plane.gpu_work(
                {
                    "challenge_id": challenge["challenge_id"],
                    "owner_id": owner_id,
                    "node_id": node_id,
                    "key_id": key_id,
                }
            )
        except PromoControlPlaneError as exc:
            message, cp_status = self._cp_error(exc)
            return (None, message, cp_status)
        if set(work) != _GPU_WORK_FIELDS:
            return (None, "Invalid GPU promo work response", HTTPStatus.BAD_GATEWAY)
        for field in (
            "challenge_id",
            "claim_class",
            "owner_id",
            "node_id",
            "key_id",
            "hardware_claim_id",
            "evidence_digest",
            "nonce",
        ):
            if work.get(field) != challenge.get(field):
                return (None, "GPU promo work binding mismatch", HTTPStatus.BAD_GATEWAY)

        try:
            dispatched = self.gpu_dispatch.dispatch(node_id=node_id, challenge=work)
        except GpuPromoDispatchClientError:
            return (None, "GPU promo provider is unavailable", HTTPStatus.SERVICE_UNAVAILABLE)
        if set(dispatched) != {"proof", "gpu_observation"}:
            return (None, "Invalid GPU promo dispatch response", HTTPStatus.BAD_GATEWAY)
        proof = dispatched.get("proof")
        observation = dispatched.get("gpu_observation")
        if not isinstance(proof, dict) or set(proof) != _PROOF_FIELDS:
            return (None, "Invalid GPU promo proof", HTTPStatus.BAD_GATEWAY)
        if not isinstance(observation, dict) or set(observation) != _GPU_OBSERVATION_FIELDS:
            return (None, "Invalid GPU promo observation", HTTPStatus.BAD_GATEWAY)
        for field in (
            "challenge_id",
            "claim_class",
            "owner_id",
            "node_id",
            "key_id",
            "hardware_claim_id",
            "evidence_digest",
            "nonce",
        ):
            if proof.get(field) != challenge.get(field):
                return (None, "GPU promo proof binding mismatch", HTTPStatus.BAD_GATEWAY)

        claimed_classes, lifetime_granted = self._lifetime_claim_state(owner_id)
        try:
            envelope = self.control_plane.verify_and_issue(
                {
                    "proof": proof,
                    "eligibility": {
                        "owner_id": owner_id,
                        "current_owner_promo_micro_units": lifetime_granted,
                        "already_claimed_classes": claimed_classes,
                        "provider_node_owner_id": owner_id,
                    },
                    "gpu_observation": observation,
                }
            )
        except PromoControlPlaneError as exc:
            message, cp_status = self._cp_error(exc)
            return (None, message, cp_status)
        return self._apply_envelope(owner_id=owner_id, envelope=envelope)

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
        if not isinstance(evidence, dict):
            return (None, "hardware_evidence must be an object", HTTPStatus.BAD_REQUEST)
        if claim_class == PROMO_GPU and self.gpu_dispatch is not None:
            return (
                None,
                "GPU promo requires the server-driven onboarding endpoint",
                HTTPStatus.BAD_REQUEST,
            )

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
        if claim_class == PROMO_GPU and self.gpu_dispatch is not None:
            return (
                None,
                "Client-supplied GPU promo proofs are disabled",
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
        return self._apply_envelope(owner_id=owner_id, envelope=envelope)
