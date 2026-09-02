"""Provider routes for unified owner accounts and owner-level payouts."""
from __future__ import annotations

from http import HTTPStatus
from typing import Any

from services.billing.accounting import AccountingStoreError
from services.billing.ledger import BillingError, MICRO_UNIT_SCALE
from services.billing.owner_accounts import OwnerAccountStore, OwnerAccountStoreError
from services.billing.owner_gateway_ledger import GatewayOwnerCreditLedger
from services.billing.owner_settlement import OwnerSettlementExecutor
from services.billing.stripe_integration import StripeIntegrationError
from services.common.config import CONFIG
from services.gateway.routes_provider import ProviderRoutesHandler


class UnifiedOwnerProviderRoutesHandler(ProviderRoutesHandler):
    """Owner-bound provider registration, status, Connect onboarding and settlement."""

    def __init__(self, *, owner_account_store: OwnerAccountStore, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.owner_account_store = owner_account_store

    def _authenticated_owner(
        self,
        headers: Any,
        *,
        bind_provider_if_missing: bool = False,
    ) -> tuple[str | None, str | None, str | None, HTTPStatus]:
        provider_node_id, err_msg, status = self.auth_manager.authenticate_provider(headers)
        if not provider_node_id:
            return (None, None, err_msg or "Unauthorized", status)
        owner_auth = self.auth_manager.authenticate_request(headers, allow_teaser=False)
        owner_id = owner_auth.owner_id or owner_auth.account_id
        if not owner_id:
            return (
                provider_node_id,
                None,
                "Provider credential is not bound to an owner",
                HTTPStatus.CONFLICT,
            )
        existing_owner = self.owner_account_store.owner_for_provider_node(provider_node_id)
        if existing_owner and existing_owner != owner_id:
            return (
                provider_node_id,
                None,
                f"Provider node {provider_node_id!r} is already owned by another account",
                HTTPStatus.CONFLICT,
            )
        if bind_provider_if_missing and not existing_owner:
            try:
                self.owner_account_store.ensure_owner(owner_id)
                self.owner_account_store.bind_provider_node(owner_id, provider_node_id)
            except OwnerAccountStoreError as exc:
                return (provider_node_id, None, str(exc), HTTPStatus.CONFLICT)
        return (provider_node_id, owner_id, None, HTTPStatus.OK)

    def _owner_settlement_executor(self) -> OwnerSettlementExecutor | None:
        executor = self.settlement_executor
        return executor if isinstance(executor, OwnerSettlementExecutor) else None

    def handle_register(
        self,
        headers: Any,
        body: dict[str, Any],
    ) -> tuple[dict[str, Any] | None, str | None, HTTPStatus]:
        provider_node_id, owner_id, err_msg, status = self._authenticated_owner(headers)
        if not provider_node_id or not owner_id:
            return (None, err_msg or "Unauthorized", status)

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
            pending = getattr(self.ledger, "owner_withdrawal_pending_micro_units", None)
            if callable(pending):
                pending_micro = int(pending(owner_id))
                result["owner_withdrawal_pending_micro_units"] = pending_micro
                result["owner_withdrawal_pending_usd"] = round(
                    pending_micro / MICRO_UNIT_SCALE,
                    4,
                )
            result["balance_model"] = "unified_owner_v1"

        executor = self._owner_settlement_executor()
        if executor:
            profile = executor.profile_store.get(owner_id)
            if profile:
                result["stripe_owner_payout"] = profile.to_dict()
        return (result, None, result_status)

    def handle_stripe_onboard(
        self,
        headers: Any,
        body: dict[str, Any],
    ) -> tuple[dict[str, Any] | None, str | None, HTTPStatus]:
        provider_node_id, owner_id, err_msg, status = self._authenticated_owner(
            headers,
            bind_provider_if_missing=True,
        )
        if not provider_node_id or not owner_id:
            return (None, err_msg or "Unauthorized", status)
        executor = self._owner_settlement_executor()
        if executor is None:
            return (None, "Owner settlement executor is not configured", HTTPStatus.SERVICE_UNAVAILABLE)
        try:
            profile = executor.create_or_refresh_owner_connect_account(
                owner_id=owner_id,
                email=str(body.get("email", "")),
                country=str(body.get("country", "DE") or "DE"),
            )
            link = executor.create_owner_onboarding_link(
                owner_id=owner_id,
                refresh_url=str(
                    body.get(
                        "refresh_url",
                        f"{CONFIG.endpoints.base_url}/providers/onboarding/refresh",
                    )
                ),
                return_url=str(
                    body.get(
                        "return_url",
                        f"{CONFIG.endpoints.base_url}/providers/onboarding/complete",
                    )
                ),
            )
            return (
                {
                    "owner_id": owner_id,
                    "provider_node_id": provider_node_id,
                    "stripe_connected_account_id": profile.stripe_connected_account_id,
                    "onboarding_url": link.onboarding_url,
                    "status": profile.stripe_onboarding_status,
                    "payout_identity_scope": "owner",
                },
                None,
                HTTPStatus.OK,
            )
        except (AccountingStoreError, StripeIntegrationError, ValueError) as exc:
            return (None, str(exc), HTTPStatus.BAD_REQUEST)

    def handle_stripe_refresh(
        self,
        headers: Any,
    ) -> tuple[dict[str, Any] | None, str | None, HTTPStatus]:
        provider_node_id, owner_id, err_msg, status = self._authenticated_owner(headers)
        if not provider_node_id or not owner_id:
            return (None, err_msg or "Unauthorized", status)
        executor = self._owner_settlement_executor()
        if executor is None:
            return (None, "Owner settlement executor is not configured", HTTPStatus.SERVICE_UNAVAILABLE)
        try:
            profile = executor.refresh_owner_connect_status(owner_id=owner_id)
            response = profile.to_dict()
            response["provider_node_id"] = provider_node_id
            response["payout_identity_scope"] = "owner"
            return (response, None, HTTPStatus.OK)
        except (AccountingStoreError, StripeIntegrationError) as exc:
            return (None, str(exc), HTTPStatus.BAD_REQUEST)

    def handle_withdraw(
        self,
        headers: Any,
        body: dict[str, Any],
    ) -> tuple[dict[str, Any] | None, str | None, HTTPStatus]:
        _provider_node_id, owner_id, err_msg, status = self._authenticated_owner(headers)
        if not owner_id:
            return (None, err_msg or "Unauthorized", status)
        executor = self._owner_settlement_executor()
        if executor is None:
            return (None, "Owner settlement executor is not configured", HTTPStatus.SERVICE_UNAVAILABLE)
        try:
            amount_micro: int | None = None
            if "amount_micro_units" in body:
                amount_micro = int(body["amount_micro_units"])
            elif "amount_usd" in body:
                amount_micro = int(round(float(body["amount_usd"]) * MICRO_UNIT_SCALE))
            if amount_micro is not None and amount_micro <= 0:
                raise ValueError("withdrawal amount must be positive")
            settlement = executor.run_owner_settlement(
                owner_id=owner_id,
                amount_micro_units=amount_micro,
                settlement_reference=str(body.get("settlement_reference", "")) or None,
            )
            return (settlement.to_dict(), None, HTTPStatus.OK)
        except (AccountingStoreError, BillingError, StripeIntegrationError, ValueError) as exc:
            return (None, str(exc), HTTPStatus.BAD_REQUEST)

    def handle_admin_settlement(
        self,
        headers: Any,
        body: dict[str, Any],
    ) -> tuple[dict[str, Any] | None, str | None, HTTPStatus]:
        is_admin, err_msg, status = self.auth_manager.authenticate_admin(headers)
        if not is_admin:
            return (None, err_msg or "Forbidden", status)
        executor = self._owner_settlement_executor()
        if executor is None:
            return (None, "Owner settlement executor is not configured", HTTPStatus.SERVICE_UNAVAILABLE)

        owner_id = str(body.get("owner_id", "")).strip()
        provider_node_id = str(body.get("provider_node_id", "")).strip()
        if not owner_id and provider_node_id:
            owner_id = self.owner_account_store.owner_for_provider_node(provider_node_id) or ""
        if not owner_id:
            return (None, "owner_id or owned provider_node_id is required", HTTPStatus.BAD_REQUEST)
        try:
            amount_micro = None
            if "amount_micro_units" in body:
                amount_micro = int(body["amount_micro_units"])
            elif "amount_usd" in body:
                amount_micro = int(round(float(body["amount_usd"]) * MICRO_UNIT_SCALE))
            settlement = executor.run_owner_settlement(
                owner_id=owner_id,
                amount_micro_units=amount_micro,
                settlement_reference=str(body.get("settlement_reference", "")) or None,
            )
            return (settlement.to_dict(), None, HTTPStatus.OK)
        except (AccountingStoreError, BillingError, StripeIntegrationError, ValueError) as exc:
            return (None, str(exc), HTTPStatus.BAD_REQUEST)
