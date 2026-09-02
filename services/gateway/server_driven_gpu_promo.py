"""Owner-authenticated, server-driven GPU onboarding promo flow.

The browser/client never submits a GPU work proof. It identifies the owned provider
node and supplies bounded hardware evidence. The gateway asks the private control
plane for a challenge, dispatches that challenge over the existing authenticated
provider control session, records server-side round-trip timing, sends the resulting
node-signed proof back to private policy, and only then applies the signed grant.
"""
from __future__ import annotations

from http import HTTPStatus
from typing import Any

from services.billing.owner_accounts import PROMO_DEVICE, PROMO_GPU, OwnerAccountStore
from services.billing.owner_credits import OwnerCreditLedger
from services.billing.promo_recovery import reconcile_existing_promo_claim
from services.billing.signed_promo_grants import PromoGrantDecisionError, SignedPromoGrantApplier
from services.gateway.auth import GatewayAuthManager
from services.gateway.promo_control_plane import PromoControlPlaneClient, PromoControlPlaneError
from services.orchestrator.authenticated_gpu_promo_transport import (
    AuthenticatedGpuPromoTransportError,
    SessionAuthenticatedGpuPromoTransport,
)

_REQUEST_FIELDS = {"node_id", "key_id", "hardware_evidence"}
_GENERIC_CHALLENGE_FIELDS = {
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
    "prompt",
    "seed",
    "n_predict",
    "model_sha256",
    "expected_llama_build_number",
    "expected_llama_build_commit",
    "timeout_ms",
}
_GPU_CHALLENGE_FIELDS = _GENERIC_CHALLENGE_FIELDS | _GPU_WORK_FIELDS


class ServerDrivenGpuPromoRoutes:
    def __init__(
        self,
        *,
        owner_store: OwnerAccountStore,
        ledger: OwnerCreditLedger,
        auth_manager: GatewayAuthManager,
        control_plane: PromoControlPlaneClient,
        applier: SignedPromoGrantApplier,
        gpu_transport: SessionAuthenticatedGpuPromoTransport,
    ) -> None:
        self.owner_store = owner_store
        self.ledger = ledger
        self.auth_manager = auth_manager
        self.control_plane = control_plane
        self.applier = applier
        self.gpu_transport = gpu_transport

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

    def _existing_result(self, owner_id: str) -> dict[str, Any] | None:
        recovered = reconcile_existing_promo_claim(
            owner_store=self.owner_store,
            ledger=self.ledger,
            owner_id=owner_id,
            claim_class=PROMO_GPU,
        )
        if recovered is None:
            return None
        balances = self.ledger.get_owner_balances(owner_id)
        return {
            "status": "already_claimed",
            "owner_id": owner_id,
            "claim_class": PROMO_GPU,
            "amount_micro_units": recovered.amount_micro_units,
            "promo_balance_micro_units": balances.promo_micro_units,
            "ledger_status": recovered.ledger_status,
        }

    def _lifetime_claim_state(self, owner_id: str) -> tuple[list[str], int]:
        claimed: list[str] = []
        lifetime = 0
        for claim_class in (PROMO_DEVICE, PROMO_GPU):
            claim = self.owner_store.promo_claim_for_owner(owner_id, claim_class)
            if claim is not None:
                claimed.append(claim_class)
                lifetime += int(claim.amount_micro_units)
        return claimed, lifetime

    @staticmethod
    def _cp_error(exc: PromoControlPlaneError) -> tuple[str, HTTPStatus]:
        if exc.status_code == 400:
            return ("Promo verification was rejected", HTTPStatus.BAD_REQUEST)
        return ("Promo verification service is unavailable", HTTPStatus.SERVICE_UNAVAILABLE)

    def handle_gpu_onboarding(
        self,
        headers: Any,
        body: dict[str, Any],
    ) -> tuple[dict[str, Any] | None, str | None, HTTPStatus]:
        owner_id, error, status = self._owner(headers)
        if owner_id is None:
            return (None, error, status)
        if set(body) != _REQUEST_FIELDS:
            return (None, "Invalid GPU promo onboarding request", HTTPStatus.BAD_REQUEST)

        node_id = str(body.get("node_id") or "").strip()
        key_id = str(body.get("key_id") or "").strip()
        evidence = body.get("hardware_evidence")
        if not node_id or len(node_id) > 128 or not key_id or len(key_id) > 128:
            return (None, "Invalid GPU promo onboarding request", HTTPStatus.BAD_REQUEST)
        if not isinstance(evidence, dict):
            return (None, "hardware_evidence must be an object", HTTPStatus.BAD_REQUEST)
        if self.owner_store.owner_for_provider_node(node_id) != owner_id:
            return (
                None,
                "GPU promo node is not owned by the authenticated owner",
                HTTPStatus.FORBIDDEN,
            )

        existing = self._existing_result(owner_id)
        if existing is not None:
            return (existing, None, HTTPStatus.OK)

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

        if set(challenge) != _GPU_CHALLENGE_FIELDS:
            return (
                None,
                "GPU promo service did not return a server-driven workload",
                HTTPStatus.BAD_GATEWAY,
            )
        if (
            str(challenge.get("claim_class")) != PROMO_GPU
            or str(challenge.get("owner_id")) != owner_id
            or str(challenge.get("node_id")) != node_id
            or str(challenge.get("key_id")) != key_id
        ):
            return (None, "GPU promo challenge binding mismatch", HTTPStatus.BAD_GATEWAY)

        timeout_ms = challenge.get("timeout_ms")
        if isinstance(timeout_ms, bool) or not isinstance(timeout_ms, int):
            return (None, "GPU promo challenge timeout is invalid", HTTPStatus.BAD_GATEWAY)
        timeout_seconds = min(300.0, timeout_ms / 1000.0 + 5.0)
        try:
            transport_result = self.gpu_transport.request_gpu_promo_challenge(
                node_id=node_id,
                challenge_document=challenge,
                timeout_seconds=timeout_seconds,
            )
        except (AuthenticatedGpuPromoTransportError, TimeoutError, OSError) as exc:
            return (
                None,
                f"Provider GPU verification failed: {str(exc)[:240]}",
                HTTPStatus.SERVICE_UNAVAILABLE,
            )

        claimed_classes, lifetime_granted = self._lifetime_claim_state(owner_id)
        try:
            envelope = self.control_plane.verify_and_issue(
                {
                    "proof": transport_result.proof,
                    "eligibility": {
                        "owner_id": owner_id,
                        "current_owner_promo_micro_units": lifetime_granted,
                        "already_claimed_classes": claimed_classes,
                        "provider_node_owner_id": owner_id,
                    },
                    "server_observation": {
                        "server_roundtrip_ms": transport_result.server_roundtrip_ms,
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


__all__ = ["ServerDrivenGpuPromoRoutes"]
