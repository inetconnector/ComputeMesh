"""ComputeMesh Gateway Billing Routes Handler.

Handles /v1/billing/balance, /v1/billing/topup, /v1/billing/checkout, and /v1/billing/webhook.
"""
from __future__ import annotations

from dataclasses import asdict
from http import HTTPStatus
from pathlib import Path
import secrets
import sys
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from services.billing.ledger import Ledger, MICRO_UNIT_SCALE
from services.billing.owner_credits import OwnerCreditLedger
from services.billing.stripe_integration import StripeIntegrationError, StripePaymentService
from services.common.config import CONFIG
from services.gateway.auth import GatewayAuthManager


class BillingRoutesHandler:
    """Dispatches billing and Stripe payment endpoints."""

    def __init__(
        self,
        ledger: Ledger,
        stripe_svc: StripePaymentService,
        auth_manager: GatewayAuthManager,
    ) -> None:
        self.ledger = ledger
        self.stripe_svc = stripe_svc
        self.auth_manager = auth_manager

    def handle_get_balance(self, headers: Any) -> tuple[dict[str, Any] | None, str | None, HTTPStatus]:
        auth = self.auth_manager.authenticate_request(headers, allow_teaser=False)
        if not auth.account_id:
            return (None, auth.error_message or "Unauthorized", auth.status_code)

        if isinstance(self.ledger, OwnerCreditLedger):
            balances = self.ledger.get_owner_balances(auth.owner_id or auth.account_id)
            return ({
                "account_id": auth.account_id,
                "owner_id": balances.owner_id,
                "balance_micro_units": balances.total_spendable_micro_units,
                "balance_usd": round(balances.total_spendable_micro_units / MICRO_UNIT_SCALE, 4),
                "earned_micro_units": balances.earned_micro_units,
                "earned_usd": round(balances.earned_micro_units / MICRO_UNIT_SCALE, 4),
                "purchased_micro_units": balances.purchased_micro_units,
                "purchased_usd": round(balances.purchased_micro_units / MICRO_UNIT_SCALE, 4),
                "promo_micro_units": balances.promo_micro_units,
                "promo_usd": round(balances.promo_micro_units / MICRO_UNIT_SCALE, 4),
                "withdrawable_micro_units": balances.withdrawable_micro_units,
                "withdrawable_usd": round(balances.withdrawable_micro_units / MICRO_UNIT_SCALE, 4),
                "available_spendable_micro_units": balances.available_spendable_micro_units,
                "currency": "usd",
                "balance_model": "unified_owner_v1",
            }, None, HTTPStatus.OK)

        balance_micro = self.ledger.get_balance(auth.account_id)
        return ({
            "account_id": auth.account_id,
            "balance_micro_units": balance_micro,
            "balance_usd": round(balance_micro / MICRO_UNIT_SCALE, 4),
            "currency": "usd",
            "balance_model": "legacy_customer_deposit",
        }, None, HTTPStatus.OK)

    def handle_post_topup(self, headers: Any, body: dict[str, Any]) -> tuple[dict[str, Any] | None, str | None, HTTPStatus]:
        auth = self.auth_manager.authenticate_request(headers, allow_teaser=False)
        if not auth.account_id:
            return (None, auth.error_message or "Unauthorized", auth.status_code)

        try:
            amount_usd = float(body.get("amount_usd", 10.0))
        except (ValueError, TypeError):
            return (None, "Invalid amount_usd format", HTTPStatus.BAD_REQUEST)

        if amount_usd <= 0:
            return (None, "amount_usd must be positive", HTTPStatus.BAD_REQUEST)

        micro_units = int(amount_usd * MICRO_UNIT_SCALE)
        if isinstance(self.ledger, OwnerCreditLedger):
            owner_id = auth.owner_id or auth.account_id
            tx = self.ledger.deposit_owner_purchased_credits(
                owner_id=owner_id,
                amount_micro_units=micro_units,
                payment_reference=f"topup_{owner_id}_{secrets.token_hex(4)}",
            )
            balances = self.ledger.get_owner_balances(owner_id)
            return ({
                "account_id": auth.account_id,
                "owner_id": owner_id,
                "amount_usd": amount_usd,
                "amount_micro_units": micro_units,
                "balance_usd": round(balances.total_spendable_micro_units / MICRO_UNIT_SCALE, 4),
                "purchased_balance_usd": round(balances.purchased_micro_units / MICRO_UNIT_SCALE, 4),
                "tx_id": tx.tx_id,
                "balance_model": "unified_owner_v1",
            }, None, HTTPStatus.OK)

        tx = self.ledger.deposit_customer_credits(
            customer_account_id=auth.account_id,
            amount_micro_units=micro_units,
            payment_reference=f"topup_{auth.account_id}_{secrets.token_hex(4)}",
        )
        return ({
            "account_id": auth.account_id,
            "amount_usd": amount_usd,
            "amount_micro_units": micro_units,
            "balance_usd": round(self.ledger.get_balance(auth.account_id) / MICRO_UNIT_SCALE, 4),
            "tx_id": tx.tx_id,
            "balance_model": "legacy_customer_deposit",
        }, None, HTTPStatus.OK)

    def handle_post_checkout(self, headers: Any, body: dict[str, Any]) -> tuple[dict[str, Any] | None, str | None, HTTPStatus]:
        auth = self.auth_manager.authenticate_request(headers, allow_teaser=False)
        if not auth.account_id:
            return (None, auth.error_message or "Unauthorized", auth.status_code)

        try:
            amount_usd = float(body.get("amount_usd", 10.0))
        except (ValueError, TypeError):
            return (None, "Invalid amount_usd format", HTTPStatus.BAD_REQUEST)

        if amount_usd <= 0:
            return (None, "amount_usd must be positive", HTTPStatus.BAD_REQUEST)

        try:
            session = self.stripe_svc.create_checkout_session(
                customer_account_id=auth.owner_id or auth.account_id,
                amount_usd=amount_usd,
                success_url=body.get("success_url", f"{CONFIG.endpoints.base_url}/billing/success?session_id={{CHECKOUT_SESSION_ID}}"),
                cancel_url=body.get("cancel_url", f"{CONFIG.endpoints.base_url}/billing/cancel"),
            )
            return (asdict(session), None, HTTPStatus.OK)
        except StripeIntegrationError as exc:
            return (None, str(exc), HTTPStatus.BAD_REQUEST)

    def handle_post_webhook(self, headers: Any, raw_body: bytes) -> tuple[dict[str, Any] | None, str | None, HTTPStatus]:
        sig_header = headers.get("Stripe-Signature", "")
        if not sig_header:
            return (None, "Missing Stripe-Signature header", HTTPStatus.BAD_REQUEST)

        try:
            result = self.stripe_svc.process_webhook_payload(
                raw_payload=raw_body,
                signature_header=sig_header,
            )
            return (result, None, HTTPStatus.OK)
        except StripeIntegrationError as exc:
            return (None, str(exc), HTTPStatus.BAD_REQUEST)
