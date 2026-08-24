#!/usr/bin/env python3
"""Stripe Connect onboarding and settlement execution for providers."""
from __future__ import annotations

from dataclasses import dataclass
import json
import os
from typing import Any
from urllib.parse import quote, urlencode
import urllib.error
import urllib.request

from services.billing.accounting import (
    AccountingStore,
    AccountingStoreError,
    ProviderAccount,
    SettlementRecord,
    utc_now,
)
from services.billing.ledger import (
    BillingError,
    Ledger,
    MICRO_UNIT_SCALE,
    MINIMUM_PAYOUT_MICRO_UNITS,
)
from services.billing.stripe_integration import StripeIntegrationError, _load_stripe_module, _stripe_get


@dataclass(frozen=True)
class ConnectedAccountResult:
    provider_node_id: str
    stripe_connected_account_id: str
    onboarding_status: str
    charges_enabled: bool
    payouts_enabled: bool
    details_submitted: bool

    def to_dict(self) -> dict[str, Any]:
        return {
            "provider_node_id": self.provider_node_id,
            "stripe_connected_account_id": self.stripe_connected_account_id,
            "onboarding_status": self.onboarding_status,
            "charges_enabled": self.charges_enabled,
            "payouts_enabled": self.payouts_enabled,
            "details_submitted": self.details_submitted,
        }


@dataclass(frozen=True)
class AccountLinkResult:
    provider_node_id: str
    stripe_connected_account_id: str
    onboarding_url: str
    expires_at: int | str

    def to_dict(self) -> dict[str, Any]:
        return {
            "provider_node_id": self.provider_node_id,
            "stripe_connected_account_id": self.stripe_connected_account_id,
            "onboarding_url": self.onboarding_url,
            "expires_at": self.expires_at,
        }


class StripeConnectService:
    """Thin wrapper around Stripe Connect APIs used by ComputeMesh."""

    def __init__(self, *, stripe_api_key: str = "", stripe_client: Any | None = None) -> None:
        self.stripe_api_key = stripe_api_key
        self.stripe_client = stripe_client
        self.connect_api_mode = os.environ.get("COMPUTEMESH_STRIPE_CONNECT_API", "v1").strip().lower()
        self.stripe_v2_api_version = os.environ.get("COMPUTEMESH_STRIPE_V2_API_VERSION", "2026-07-29.preview").strip()
        if self.stripe_api_key and self.stripe_client is None:
            stripe = _load_stripe_module()
            stripe.api_key = self.stripe_api_key
            self.stripe_client = stripe

    def require_configured(self) -> None:
        if not self.stripe_api_key:
            raise StripeIntegrationError("STRIPE_API_KEY is required for Stripe Connect")
        if self.connect_api_mode == "v2":
            return
        if self.stripe_client is None:
            raise StripeIntegrationError("Official Stripe client is not configured")

    def create_connected_account(
        self,
        *,
        provider_node_id: str,
        email: str = "",
        country: str = "DE",
    ) -> ConnectedAccountResult:
        self.require_configured()
        if self.connect_api_mode == "v2":
            return self._create_connected_account_v2(
                provider_node_id=provider_node_id,
                email=email,
                country=country,
            )
        params: dict[str, Any] = {
            "type": "express",
            "country": country.upper(),
            "capabilities": {"transfers": {"requested": True}},
            "metadata": {
                "provider_node_id": provider_node_id,
                "product": "computemesh_provider_payouts",
            },
        }
        if email:
            params["email"] = email
        try:
            account = self.stripe_client.Account.create(**params)
        except Exception as exc:
            if self._should_fallback_to_v2(exc):
                return self._create_connected_account_v2(
                    provider_node_id=provider_node_id,
                    email=email,
                    country=country,
                )
            raise StripeIntegrationError(f"Stripe connected account creation failed: {exc}") from exc
        return self._account_result(provider_node_id=provider_node_id, account=account)

    def create_account_link(
        self,
        *,
        stripe_connected_account_id: str,
        refresh_url: str,
        return_url: str,
    ) -> AccountLinkResult:
        self.require_configured()
        if self.connect_api_mode == "v2":
            return self._create_account_link_v2(
                stripe_connected_account_id=stripe_connected_account_id,
                refresh_url=refresh_url,
                return_url=return_url,
            )
        try:
            link = self.stripe_client.AccountLink.create(
                account=stripe_connected_account_id,
                refresh_url=refresh_url,
                return_url=return_url,
                type="account_onboarding",
            )
        except Exception as exc:
            if self._should_fallback_to_v2(exc):
                return self._create_account_link_v2(
                    stripe_connected_account_id=stripe_connected_account_id,
                    refresh_url=refresh_url,
                    return_url=return_url,
                )
            raise StripeIntegrationError(f"Stripe account onboarding link creation failed: {exc}") from exc
        return AccountLinkResult(
            provider_node_id="",
            stripe_connected_account_id=stripe_connected_account_id,
            onboarding_url=str(_stripe_get(link, "url", "")),
            expires_at=int(_stripe_get(link, "expires_at", 0) or 0),
        )

    def retrieve_connected_account(
        self,
        *,
        provider_node_id: str,
        stripe_connected_account_id: str,
    ) -> ConnectedAccountResult:
        self.require_configured()
        if self.connect_api_mode == "v2":
            return self._retrieve_connected_account_v2(
                provider_node_id=provider_node_id,
                stripe_connected_account_id=stripe_connected_account_id,
            )
        try:
            account = self.stripe_client.Account.retrieve(stripe_connected_account_id)
        except Exception as exc:
            if self._should_fallback_to_v2(exc):
                return self._retrieve_connected_account_v2(
                    provider_node_id=provider_node_id,
                    stripe_connected_account_id=stripe_connected_account_id,
                )
            raise StripeIntegrationError(f"Stripe connected account retrieval failed: {exc}") from exc
        return self._account_result(provider_node_id=provider_node_id, account=account)

    def transfer_to_connected_account(
        self,
        *,
        settlement_id: str,
        provider_node_id: str,
        amount_micro_units: int,
        stripe_connected_account_id: str,
        currency: str = "usd",
    ) -> str:
        self.require_configured()
        if amount_micro_units <= 0:
            raise StripeIntegrationError("transfer amount must be positive")
        amount_cents = amount_micro_units // (MICRO_UNIT_SCALE // 100)
        if amount_cents <= 0:
            raise StripeIntegrationError("transfer amount is below Stripe cent precision")
        try:
            transfer = self.stripe_client.Transfer.create(
                amount=amount_cents,
                currency=currency.lower(),
                destination=stripe_connected_account_id,
                transfer_group=settlement_id,
                metadata={
                    "settlement_id": settlement_id,
                    "provider_node_id": provider_node_id,
                    "amount_micro_units": str(amount_micro_units),
                    "product": "computemesh_provider_settlement",
                },
                idempotency_key=f"computemesh:{settlement_id}",
            )
        except TypeError:
            # Older/injected fake clients may not model keyword-only request options.
            transfer = self.stripe_client.Transfer.create(
                amount=amount_cents,
                currency=currency.lower(),
                destination=stripe_connected_account_id,
                transfer_group=settlement_id,
                metadata={
                    "settlement_id": settlement_id,
                    "provider_node_id": provider_node_id,
                    "amount_micro_units": str(amount_micro_units),
                    "product": "computemesh_provider_settlement",
                },
            )
        except Exception as exc:
            raise StripeIntegrationError(f"Stripe transfer failed: {exc}") from exc
        transfer_id = str(_stripe_get(transfer, "id", ""))
        if not transfer_id:
            raise StripeIntegrationError("Stripe transfer did not return an id")
        return transfer_id

    @staticmethod
    def _account_result(*, provider_node_id: str, account: Any) -> ConnectedAccountResult:
        charges_enabled = bool(_stripe_get(account, "charges_enabled", False))
        payouts_enabled = bool(_stripe_get(account, "payouts_enabled", False))
        details_submitted = bool(_stripe_get(account, "details_submitted", False))
        if payouts_enabled and details_submitted:
            status = "ready"
        elif details_submitted:
            status = "pending_verification"
        else:
            status = "needs_onboarding"
        return ConnectedAccountResult(
            provider_node_id=provider_node_id,
            stripe_connected_account_id=str(_stripe_get(account, "id", "")),
            onboarding_status=status,
            charges_enabled=charges_enabled,
            payouts_enabled=payouts_enabled,
            details_submitted=details_submitted,
        )

    def _create_connected_account_v2(
        self,
        *,
        provider_node_id: str,
        email: str = "",
        country: str = "DE",
    ) -> ConnectedAccountResult:
        payload: dict[str, Any] = {
            "display_name": f"ComputeMesh provider {provider_node_id}",
            "dashboard": "express",
            "identity": {"country": country.lower()},
            "defaults": {
                "responsibilities": {
                    "fees_collector": "application",
                    "losses_collector": "application",
                }
            },
            "configuration": {
                "recipient": {
                    "capabilities": {
                        "stripe_balance": {
                            "stripe_transfers": {
                                "requested": True,
                            }
                        }
                    }
                }
            },
            "metadata": {
                "provider_node_id": provider_node_id,
                "product": "computemesh_provider_payouts",
            },
            "include": ["configuration.recipient", "identity", "requirements"],
        }
        if email:
            payload["contact_email"] = email
        account = self._stripe_v2_request("POST", "/v2/core/accounts", payload=payload)
        return self._account_result_v2(provider_node_id=provider_node_id, account=account)

    def _create_account_link_v2(
        self,
        *,
        stripe_connected_account_id: str,
        refresh_url: str,
        return_url: str,
    ) -> AccountLinkResult:
        payload = {
            "account": stripe_connected_account_id,
            "use_case": {
                "type": "account_onboarding",
                "account_onboarding": {
                    "configurations": ["recipient"],
                    "refresh_url": refresh_url,
                    "return_url": return_url,
                },
            },
        }
        link = self._stripe_v2_request("POST", "/v2/core/account_links", payload=payload)
        return AccountLinkResult(
            provider_node_id="",
            stripe_connected_account_id=stripe_connected_account_id,
            onboarding_url=str(link.get("url", "")),
            expires_at=link.get("expires_at", ""),
        )

    def _retrieve_connected_account_v2(
        self,
        *,
        provider_node_id: str,
        stripe_connected_account_id: str,
    ) -> ConnectedAccountResult:
        query = urlencode([
            ("include[0]", "configuration.recipient"),
            ("include[1]", "identity"),
            ("include[2]", "requirements"),
            ("include[3]", "defaults"),
        ])
        account_id = quote(stripe_connected_account_id, safe="")
        account = self._stripe_v2_request("GET", f"/v2/core/accounts/{account_id}?{query}")
        return self._account_result_v2(provider_node_id=provider_node_id, account=account)

    def _stripe_v2_request(self, method: str, path: str, *, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        raw_body = b""
        headers = {
            "Authorization": f"Bearer {self.stripe_api_key}",
            "Stripe-Version": self.stripe_v2_api_version,
        }
        if payload is not None:
            raw_body = json.dumps(payload, separators=(",", ":")).encode("utf-8")
            headers["Content-Type"] = "application/json"
        req = urllib.request.Request(
            f"https://api.stripe.com{path}",
            data=raw_body if method.upper() != "GET" else None,
            method=method.upper(),
            headers=headers,
        )
        try:
            with urllib.request.urlopen(req, timeout=30) as res:
                return json.loads(res.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            raise StripeIntegrationError(f"Stripe Accounts v2 API request failed: HTTP {exc.code} {detail}") from exc
        except Exception as exc:
            raise StripeIntegrationError(f"Stripe Accounts v2 API request failed: {exc}") from exc

    @staticmethod
    def _account_result_v2(*, provider_node_id: str, account: dict[str, Any]) -> ConnectedAccountResult:
        recipient = (account.get("configuration") or {}).get("recipient") or {}
        capabilities = recipient.get("capabilities") or {}
        stripe_balance = capabilities.get("stripe_balance") or {}
        transfers = stripe_balance.get("stripe_transfers") or {}
        transfer_status = str(transfers.get("status", "") or "")
        status_details = transfers.get("status_details") or []
        payouts_enabled = transfer_status == "active"
        details_submitted = transfer_status == "active" or (transfer_status and transfer_status != "restricted")
        if payouts_enabled:
            onboarding_status = "ready"
        elif any((d or {}).get("code") == "requirements_past_due" for d in status_details if isinstance(d, dict)):
            onboarding_status = "requirements_past_due"
        else:
            onboarding_status = "needs_onboarding"
        return ConnectedAccountResult(
            provider_node_id=provider_node_id,
            stripe_connected_account_id=str(account.get("id", "")),
            onboarding_status=onboarding_status,
            charges_enabled=False,
            payouts_enabled=payouts_enabled,
            details_submitted=details_submitted,
        )

    @staticmethod
    def _should_fallback_to_v2(exc: Exception) -> bool:
        msg = str(exc)
        return "Accounts v2" in msg or "POST /v2/core/accounts" in msg or "Accounts v1" in msg


class SettlementExecutor:
    """Coordinates Stripe Connect transfers with internal ledger payout entries."""

    def __init__(
        self,
        *,
        ledger: Ledger,
        account_store: AccountingStore,
        stripe_connect: StripeConnectService,
    ) -> None:
        self.ledger = ledger
        self.account_store = account_store
        self.stripe_connect = stripe_connect

    def run_provider_settlement(self, *, provider_node_id: str) -> SettlementRecord:
        provider = self.account_store.get_provider(provider_node_id)
        if not provider:
            raise AccountingStoreError(f"unknown provider {provider_node_id}")
        if not provider.stripe_connected_account_id:
            raise AccountingStoreError(f"provider {provider_node_id} has no Stripe connected account")
        if not provider.payouts_enabled:
            raise AccountingStoreError(f"provider {provider_node_id} Stripe payouts are not enabled")

        balance = self.ledger.get_balance(provider.ledger_account_id)
        if balance < MINIMUM_PAYOUT_MICRO_UNITS:
            raise BillingError(
                f"provider balance {balance} below minimum payout threshold {MINIMUM_PAYOUT_MICRO_UNITS}"
            )

        settlement_id = f"settle_provider_{provider_node_id}_{balance}"
        now = utc_now()
        pending = SettlementRecord(
            settlement_id=settlement_id,
            account_kind="provider",
            account_id=provider_node_id,
            amount_micro_units=balance,
            amount_usd=round(balance / MICRO_UNIT_SCALE, 4),
            stripe_connected_account_id=provider.stripe_connected_account_id,
            destination=provider.payout_wallet_address or provider.stripe_connected_account_id,
            status="pending",
            created_at=now,
            updated_at=now,
        )
        self.account_store.upsert_settlement(pending)

        settlement_currency = os.environ.get("COMPUTEMESH_STRIPE_SETTLEMENT_CURRENCY", "usd").strip().lower() or "usd"
        transfer_id = self.stripe_connect.transfer_to_connected_account(
            settlement_id=settlement_id,
            provider_node_id=provider_node_id,
            amount_micro_units=balance,
            stripe_connected_account_id=provider.stripe_connected_account_id,
            currency=settlement_currency,
        )
        tx, _summary = self.ledger.create_provider_payout(
            provider_node_id=provider_node_id,
            wallet_address=provider.stripe_connected_account_id,
            settlement_reference=settlement_id,
        )
        completed = SettlementRecord(
            settlement_id=settlement_id,
            account_kind="provider",
            account_id=provider_node_id,
            amount_micro_units=balance,
            amount_usd=round(balance / MICRO_UNIT_SCALE, 4),
            ledger_tx_id=tx.tx_id,
            stripe_transfer_id=transfer_id,
            stripe_connected_account_id=provider.stripe_connected_account_id,
            destination=provider.payout_wallet_address or provider.stripe_connected_account_id,
            status="completed",
            created_at=pending.created_at,
            updated_at=utc_now(),
        )
        return self.account_store.upsert_settlement(completed)

    def create_or_refresh_provider_connect_account(
        self,
        *,
        provider_node_id: str,
        display_name: str = "",
        payout_wallet_address: str = "",
        email: str = "",
        country: str = "DE",
    ) -> ProviderAccount:
        provider = self.account_store.upsert_provider(
            provider_node_id=provider_node_id,
            display_name=display_name,
            payout_wallet_address=payout_wallet_address,
        )
        if provider.stripe_connected_account_id:
            status = self.stripe_connect.retrieve_connected_account(
                provider_node_id=provider.provider_node_id,
                stripe_connected_account_id=provider.stripe_connected_account_id,
            )
        else:
            status = self.stripe_connect.create_connected_account(
                provider_node_id=provider.provider_node_id,
                email=email,
                country=country,
            )
            self.account_store.attach_stripe_account(
                provider_node_id=provider.provider_node_id,
                stripe_connected_account_id=status.stripe_connected_account_id,
                onboarding_status=status.onboarding_status,
            )
        return self.account_store.update_stripe_account_status(
            provider_node_id=provider.provider_node_id,
            onboarding_status=status.onboarding_status,
            charges_enabled=status.charges_enabled,
            payouts_enabled=status.payouts_enabled,
            details_submitted=status.details_submitted,
        )

    def create_provider_onboarding_link(
        self,
        *,
        provider_node_id: str,
        refresh_url: str,
        return_url: str,
    ) -> AccountLinkResult:
        provider = self.account_store.get_provider(provider_node_id)
        if not provider or not provider.stripe_connected_account_id:
            raise AccountingStoreError(f"provider {provider_node_id} has no Stripe connected account")
        link = self.stripe_connect.create_account_link(
            stripe_connected_account_id=provider.stripe_connected_account_id,
            refresh_url=refresh_url,
            return_url=return_url,
        )
        return AccountLinkResult(
            provider_node_id=provider_node_id,
            stripe_connected_account_id=provider.stripe_connected_account_id,
            onboarding_url=link.onboarding_url,
            expires_at=link.expires_at,
        )

    def refresh_provider_connect_status(self, *, provider_node_id: str) -> ProviderAccount:
        provider = self.account_store.get_provider(provider_node_id)
        if not provider:
            raise AccountingStoreError(f"unknown provider {provider_node_id}")
        if not provider.stripe_connected_account_id:
            raise AccountingStoreError(f"provider {provider_node_id} has no Stripe connected account")
        status = self.stripe_connect.retrieve_connected_account(
            provider_node_id=provider.provider_node_id,
            stripe_connected_account_id=provider.stripe_connected_account_id,
        )
        return self.account_store.update_stripe_account_status(
            provider_node_id=provider.provider_node_id,
            onboarding_status=status.onboarding_status,
            charges_enabled=status.charges_enabled,
            payouts_enabled=status.payouts_enabled,
            details_submitted=status.details_submitted,
        )
