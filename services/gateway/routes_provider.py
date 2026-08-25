"""ComputeMesh Gateway Provider & Settlement Routes Handler.

Handles /v1/providers/register, /v1/providers/stripe/onboard,
/v1/providers/stripe/refresh, and /v1/admin/settlements/provider.
"""
from __future__ import annotations

from http import HTTPStatus
import os
from pathlib import Path
import sys
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from services.billing.accounting import AccountingStore, AccountingStoreError
from services.billing.ledger import InsufficientBalanceError, Ledger, MICRO_UNIT_SCALE
from services.billing.stripe_connect import SettlementExecutor, StripeConnectService
from services.billing.stripe_integration import StripeIntegrationError
from services.common.config import CONFIG
from services.gateway.auth import GatewayAuthManager, extract_bearer_token


class ProviderRoutesHandler:
    """Dispatches provider registration, Stripe Connect onboarding, and settlements."""

    def __init__(
        self,
        account_store: AccountingStore | None,
        settlement_executor: SettlementExecutor | None,
        auth_manager: GatewayAuthManager,
        ledger: Ledger | None = None,
    ) -> None:
        self.account_store = account_store
        self.settlement_executor = settlement_executor
        self.auth_manager = auth_manager
        self.ledger = ledger

    def handle_register(self, headers: Any, body: dict[str, Any]) -> tuple[dict[str, Any] | None, str | None, HTTPStatus]:
        if not self.account_store:
            return (None, "Provider account store is not configured", HTTPStatus.SERVICE_UNAVAILABLE)

        node_id = str(body.get("provider_node_id", "")).strip()
        if not node_id:
            token = extract_bearer_token(headers)
            if token.startswith("cm_provider_"):
                node_id = token.removeprefix("cm_provider_").strip()

        if not node_id:
            return (None, "provider_node_id is required", HTTPStatus.BAD_REQUEST)

        account = self.account_store.upsert_provider(
            provider_node_id=node_id,
            display_name=str(body.get("display_name", "")),
            payout_wallet_address=str(body.get("payout_wallet_address", "")),
        )
        return (account.to_dict(), None, HTTPStatus.OK)

    def handle_status(self, headers: Any) -> tuple[dict[str, Any] | None, str | None, HTTPStatus]:
        provider_node_id, err_msg, status = self.auth_manager.authenticate_provider(headers)
        if not provider_node_id:
            return (None, err_msg or "Unauthorized", status)

        if not self.account_store:
            return (None, "Provider account store is not configured", HTTPStatus.SERVICE_UNAVAILABLE)

        provider = self.account_store.get_provider(provider_node_id)
        if not provider:
            return (None, "Provider account not found", HTTPStatus.NOT_FOUND)

        res = provider.to_dict()
        ledger_account = f"provider:{provider_node_id}"
        balance_micro = self.ledger.get_balance(ledger_account) if self.ledger else 0
        res["balance_micro_units"] = balance_micro
        res["balance_usd"] = round(balance_micro / MICRO_UNIT_SCALE, 4)
        return (res, None, HTTPStatus.OK)

    def handle_admin_list_providers(self, headers: Any) -> tuple[dict[str, Any] | None, str | None, HTTPStatus]:
        is_admin, err_msg, status = self.auth_manager.authenticate_admin(headers)
        if not is_admin:
            return (None, err_msg or "Forbidden", status)
        if not self.account_store:
            return (None, "Provider account store is not configured", HTTPStatus.SERVICE_UNAVAILABLE)
        providers = self.account_store.list_providers()
        return ({"data": [p.to_dict() for p in providers]}, None, HTTPStatus.OK)

    def handle_stripe_onboard(self, headers: Any, body: dict[str, Any]) -> tuple[dict[str, Any] | None, str | None, HTTPStatus]:
        provider_node_id, err_msg, status = self.auth_manager.authenticate_provider(headers)
        if not provider_node_id:
            return (None, err_msg or "Unauthorized", status)

        if not self.account_store:
            return (None, "Provider account store is not configured", HTTPStatus.SERVICE_UNAVAILABLE)

        try:
            stripe_connect = getattr(self.settlement_executor, "stripe_connect", None) or StripeConnectService(
                stripe_api_key=os.environ.get("STRIPE_API_KEY", "").strip()
            )
            res = stripe_connect.create_connected_account(provider_node_id=provider_node_id)
            self.account_store.attach_stripe_account(
                provider_node_id=provider_node_id,
                stripe_connected_account_id=res.stripe_connected_account_id,
            )
            link_res = stripe_connect.create_account_link(
                stripe_connected_account_id=res.stripe_connected_account_id,
                refresh_url=body.get("refresh_url", f"{CONFIG.endpoints.base_url}/providers/onboarding/refresh"),
                return_url=body.get("return_url", f"{CONFIG.endpoints.base_url}/providers/onboarding/complete"),
            )
            return ({
                "provider_node_id": provider_node_id,
                "stripe_connected_account_id": res.stripe_connected_account_id,
                "onboarding_url": link_res.onboarding_url,
                "status": res.onboarding_status,
            }, None, HTTPStatus.OK)
        except StripeIntegrationError as exc:
            return (None, str(exc), HTTPStatus.BAD_REQUEST)

    def handle_stripe_refresh(self, headers: Any) -> tuple[dict[str, Any] | None, str | None, HTTPStatus]:
        provider_node_id, err_msg, status = self.auth_manager.authenticate_provider(headers)
        if not provider_node_id:
            return (None, err_msg or "Unauthorized", status)

        if not self.account_store:
            return (None, "Provider account store is not configured", HTTPStatus.SERVICE_UNAVAILABLE)

        provider = self.account_store.get_provider(provider_node_id)
        if not provider or not provider.stripe_connected_account_id:
            return (None, "No Stripe Connected Account attached to provider", HTTPStatus.BAD_REQUEST)

        try:
            stripe_connect = getattr(self.settlement_executor, "stripe_connect", None) or StripeConnectService(
                stripe_api_key=os.environ.get("STRIPE_API_KEY", "").strip()
            )
            status_res = stripe_connect.retrieve_connected_account(
                provider_node_id=provider_node_id,
                stripe_connected_account_id=provider.stripe_connected_account_id,
            )
            updated = self.account_store.update_stripe_account_status(
                provider_node_id=provider_node_id,
                onboarding_status=status_res.onboarding_status,
                charges_enabled=status_res.charges_enabled,
                payouts_enabled=status_res.payouts_enabled,
                details_submitted=status_res.details_submitted,
            )
            return (updated.to_dict(), None, HTTPStatus.OK)
        except StripeIntegrationError as exc:
            return (None, str(exc), HTTPStatus.BAD_REQUEST)

    def handle_admin_settlement(self, headers: Any, body: dict[str, Any]) -> tuple[dict[str, Any] | None, str | None, HTTPStatus]:
        is_admin, err_msg, status = self.auth_manager.authenticate_admin(headers)
        if not is_admin:
            return (None, err_msg or "Forbidden", status)

        if not self.settlement_executor:
            return (None, "Settlement executor is not configured", HTTPStatus.SERVICE_UNAVAILABLE)

        try:
            settlement = self.settlement_executor.run_provider_settlement(
                provider_node_id=str(body.get("provider_node_id", "")),
            )
            return (settlement.to_dict(), None, HTTPStatus.OK)
        except (AccountingStoreError, InsufficientBalanceError, StripeIntegrationError, Exception) as exc:
            return (None, str(exc), HTTPStatus.BAD_REQUEST)

    def handle_admin_list_settlements(self, headers: Any, query: dict[str, list[str]]) -> tuple[dict[str, Any] | None, str | None, HTTPStatus]:
        is_admin, err_msg, status = self.auth_manager.authenticate_admin(headers)
        if not is_admin:
            return (None, err_msg or "Forbidden", status)
        if not self.account_store:
            return (None, "Provider account store is not configured", HTTPStatus.SERVICE_UNAVAILABLE)
        status_filter = query.get("status", [None])[0]
        try:
            limit = int(query.get("limit", ["50"])[0])
        except ValueError:
            limit = 50
        settlements = self.account_store.list_settlements(status=status_filter, limit=limit)
        return ({"data": [s.to_dict() for s in settlements]}, None, HTTPStatus.OK)
