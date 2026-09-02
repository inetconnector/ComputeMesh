"""Provider routes for unified owner accounts."""
from __future__ import annotations

from http import HTTPStatus
from typing import Any

from services.billing.owner_accounts import OwnerAccountStore, OwnerAccountStoreError
from services.billing.owner_gateway_ledger import GatewayOwnerCreditLedger
from services.billing.ledger import MICRO_UNIT_SCALE
from services.gateway.routes_provider import ProviderRoutesHandler


class UnifiedOwnerProviderRoutesHandler(ProviderRoutesHandler):
    """Adds durable provider-node ownership to the existing provider account surface."""

    def __init__(self, *, owner_account_store: OwnerAccountStore, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.owner_account_store = owner_account_store

    def handle_register(
        self,
        headers: Any,
        body: dict[str, Any],
    ) -> tuple[dict[str, Any] | None, str | None, HTTPStatus]:
        provider_node_id, err_msg, status = self.auth_manager.authenticate_provider(headers)
        if not provider_node_id:
            return (None, err_msg or "Unauthorized", status)

        owner_auth = self.auth_manager.authenticate_request(headers, allow_teaser=False)
        owner_id = owner_auth.owner_id or owner_auth.account_id
        if not owner_id:
            return (None, "Provider credential is not bound to an owner", HTTPStatus.CONFLICT)

        existing_owner = self.owner_account_store.owner_for_provider_node(provider_node_id)
        if existing_owner and existing_owner != owner_id:
            return (
                None,
                f"Provider node {provider_node_id!r} is already owned by another account",
                HTTPStatus.CONFLICT,
            )

        result, error, result_status = super().handle_register(headers, body)
        if result is None:
            return (result, error, result_status)

        try:
            self.owner_account_store.ensure_owner(owner_id)
            self.owner_account_store.bind_provider_node(owner_id, provider_node_id)
        except OwnerAccountStoreError as exc:
            return (None, str(exc), HTTPStatus.CONFLICT)

        result["owner_id"] = owner_id
        result["owner_binding"] = "verified_credential_binding_v1"
        return (result, None, result_status)

    def handle_status(
        self,
        headers: Any,
    ) -> tuple[dict[str, Any] | None, str | None, HTTPStatus]:
        provider_node_id, err_msg, status = self.auth_manager.authenticate_provider(headers)
        if not provider_node_id:
            return (None, err_msg or "Unauthorized", status)

        result, error, result_status = super().handle_status(headers)
        if result is None:
            return (result, error, result_status)

        owner_id = self.owner_account_store.owner_for_provider_node(provider_node_id)
        if not owner_id:
            return (
                None,
                "Provider node has no unified owner binding",
                HTTPStatus.CONFLICT,
            )

        result["owner_id"] = owner_id
        if isinstance(self.ledger, GatewayOwnerCreditLedger):
            balances = self.ledger.get_owner_balances(owner_id)
            # Preserve the old per-node field only as clearly labelled legacy data;
            # unified earnings belong to the owner, not to one API key or node.
            result["legacy_provider_node_balance_micro_units"] = result.get(
                "balance_micro_units",
                0,
            )
            result["owner_balance_micro_units"] = balances.total_spendable_micro_units
            result["owner_balance_usd"] = round(
                balances.total_spendable_micro_units / MICRO_UNIT_SCALE,
                4,
            )
            result["owner_earned_micro_units"] = balances.earned_micro_units
            result["owner_earned_usd"] = round(
                balances.earned_micro_units / MICRO_UNIT_SCALE,
                4,
            )
            result["owner_withdrawable_micro_units"] = balances.withdrawable_micro_units
            result["owner_withdrawable_usd"] = round(
                balances.withdrawable_micro_units / MICRO_UNIT_SCALE,
                4,
            )
            result["balance_model"] = "unified_owner_v1"
        return (result, None, result_status)
