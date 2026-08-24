#!/usr/bin/env python3
"""ComputeMesh Stripe Checkout and signed webhook payment integration.

Creates real Stripe Checkout Sessions when configured with the official Stripe
SDK and credits customer prepaid compute balances only after a verified Stripe
webhook confirms the Checkout Session payment.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal, ROUND_HALF_UP
import json
import os
from pathlib import Path
from typing import Any, Callable

from services.billing.ledger import (
    DuplicateEventError,
    Ledger,
    MICRO_UNIT_SCALE,
)


class StripeIntegrationError(Exception):
    """Raised on payment session or signature validation failures."""


@dataclass(frozen=True)
class CheckoutSessionResult:
    session_id: str
    checkout_url: str
    customer_account_id: str
    amount_usd: float
    amount_micro_units: int
    created_at: str
    currency: str
    stripe_customer_id: str
    payment_intent_id: str
    livemode: bool


@dataclass(frozen=True)
class StripeSessionRecord:
    session_id: str
    customer_account_id: str
    amount_micro_units: int
    currency: str
    checkout_url: str
    stripe_customer_id: str = ""
    payment_intent_id: str = ""
    livemode: bool = False
    credited_transaction_id: str = ""
    status: str = "created"
    created_at: str = ""
    updated_at: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "session_id": self.session_id,
            "customer_account_id": self.customer_account_id,
            "amount_micro_units": self.amount_micro_units,
            "currency": self.currency,
            "checkout_url": self.checkout_url,
            "stripe_customer_id": self.stripe_customer_id,
            "payment_intent_id": self.payment_intent_id,
            "livemode": self.livemode,
            "credited_transaction_id": self.credited_transaction_id,
            "status": self.status,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }


class StripeSessionStore:
    """Small JSON-backed store for Stripe session/payment IDs.

    This is intentionally narrow: it persists the Stripe identifiers required to
    reconcile Checkout webhooks with internal customer accounts. The financial
    source of truth remains the double-entry ledger.
    """

    def __init__(self, storage_path: Path) -> None:
        self.storage_path = Path(storage_path)
        self._records: dict[str, StripeSessionRecord] = {}
        if self.storage_path.exists():
            self._load()

    def _load(self) -> None:
        raw = json.loads(self.storage_path.read_text(encoding="utf-8"))
        if not isinstance(raw, dict):
            raise StripeIntegrationError(f"Stripe session store {self.storage_path} must contain a JSON object")
        for session_id, record in raw.items():
            if isinstance(record, dict):
                self._records[str(session_id)] = StripeSessionRecord(
                    session_id=str(record.get("session_id") or session_id),
                    customer_account_id=str(record.get("customer_account_id", "")),
                    amount_micro_units=int(record.get("amount_micro_units", 0)),
                    currency=str(record.get("currency", "usd")),
                    checkout_url=str(record.get("checkout_url", "")),
                    stripe_customer_id=str(record.get("stripe_customer_id", "")),
                    payment_intent_id=str(record.get("payment_intent_id", "")),
                    livemode=bool(record.get("livemode", False)),
                    credited_transaction_id=str(record.get("credited_transaction_id", "")),
                    status=str(record.get("status", "created")),
                    created_at=str(record.get("created_at", "")),
                    updated_at=str(record.get("updated_at", "")),
                )

    def _flush(self) -> None:
        self.storage_path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.storage_path.with_suffix(self.storage_path.suffix + ".tmp")
        tmp.write_text(
            json.dumps({sid: rec.to_dict() for sid, rec in sorted(self._records.items())}, indent=2) + "\n",
            encoding="utf-8",
        )
        tmp.replace(self.storage_path)

    def get(self, session_id: str) -> StripeSessionRecord | None:
        return self._records.get(session_id)

    def upsert(self, record: StripeSessionRecord) -> None:
        self._records[record.session_id] = record
        self._flush()

    def mark_credited(
        self,
        *,
        session_id: str,
        transaction_id: str,
        stripe_customer_id: str = "",
        payment_intent_id: str = "",
        livemode: bool | None = None,
    ) -> None:
        existing = self.get(session_id)
        if not existing:
            now = _utc_now()
            existing = StripeSessionRecord(
                session_id=session_id,
                customer_account_id="",
                amount_micro_units=0,
                currency="usd",
                checkout_url="",
                created_at=now,
            )
        self.upsert(
            StripeSessionRecord(
                session_id=existing.session_id,
                customer_account_id=existing.customer_account_id,
                amount_micro_units=existing.amount_micro_units,
                currency=existing.currency,
                checkout_url=existing.checkout_url,
                stripe_customer_id=stripe_customer_id or existing.stripe_customer_id,
                payment_intent_id=payment_intent_id or existing.payment_intent_id,
                livemode=existing.livemode if livemode is None else livemode,
                credited_transaction_id=transaction_id,
                status="credited",
                created_at=existing.created_at,
                updated_at=_utc_now(),
            )
        )


WebhookVerifier = Callable[[bytes, str, str], dict[str, Any]]


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _stripe_get(obj: Any, key: str, default: Any = None) -> Any:
    if isinstance(obj, dict):
        return obj.get(key, default)
    return getattr(obj, key, default)


def _stripe_to_plain(obj: Any) -> Any:
    """Convert Stripe SDK resource objects into recursive plain Python data."""
    if isinstance(obj, dict):
        return {str(k): _stripe_to_plain(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_stripe_to_plain(v) for v in obj]
    if hasattr(obj, "to_dict_recursive"):
        return _stripe_to_plain(obj.to_dict_recursive())
    if hasattr(obj, "_to_dict_recursive"):
        return _stripe_to_plain(obj._to_dict_recursive())
    if hasattr(obj, "to_dict"):
        return _stripe_to_plain(obj.to_dict())
    return obj


def _amount_to_cents(amount_usd: float) -> int:
    amount = Decimal(str(amount_usd))
    return int((amount * Decimal("100")).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def _cents_to_micro_units(amount_cents: int) -> int:
    return int(amount_cents) * (MICRO_UNIT_SCALE // 100)


def _load_stripe_module() -> Any:
    try:
        import stripe  # type: ignore
    except Exception as exc:
        raise StripeIntegrationError(
            "The official Stripe Python SDK is required for live payments. Install package 'stripe'."
        ) from exc
    return stripe


class StripePaymentService:
    def __init__(
        self,
        ledger: Ledger,
        webhook_secret: str | None = None,
        stripe_api_key: str | None = None,
        session_store: StripeSessionStore | None = None,
        webhook_event_store: Any | None = None,
        stripe_client: Any | None = None,
        webhook_verifier: WebhookVerifier | None = None,
        require_live_configuration: bool = False,
    ) -> None:
        self.ledger = ledger
        self.webhook_secret = webhook_secret or ""
        self.stripe_api_key = stripe_api_key or ""
        self.session_store = session_store
        self.webhook_event_store = webhook_event_store
        self.stripe_client = stripe_client
        self.webhook_verifier = webhook_verifier
        self.require_live_configuration = require_live_configuration

        if self.stripe_api_key and self.stripe_client is None:
            stripe = _load_stripe_module()
            stripe.api_key = self.stripe_api_key
            self.stripe_client = stripe

        if self.require_live_configuration:
            self._require_live_configuration()

    @classmethod
    def from_env(cls, *, ledger: Ledger) -> "StripePaymentService":
        session_store_path = os.environ.get("COMPUTEMESH_STRIPE_SESSION_STORE", "").strip()
        session_store = StripeSessionStore(Path(session_store_path)) if session_store_path else None
        return cls(
            ledger=ledger,
            webhook_secret=os.environ.get("STRIPE_WEBHOOK_SECRET", "").strip(),
            stripe_api_key=os.environ.get("STRIPE_API_KEY", "").strip(),
            session_store=session_store,
            require_live_configuration=bool(os.environ.get("STRIPE_API_KEY", "").strip()),
        )

    def _require_live_configuration(self) -> None:
        if not self.stripe_api_key:
            raise StripeIntegrationError("STRIPE_API_KEY is required for Stripe Checkout")
        if self.stripe_client is None:
            raise StripeIntegrationError("Official Stripe client is not configured")
        if self.session_store is None:
            raise StripeIntegrationError("COMPUTEMESH_STRIPE_SESSION_STORE is required for durable Stripe reconciliation")

    def _require_webhook_configuration(self) -> None:
        if not self.webhook_secret:
            raise StripeIntegrationError("STRIPE_WEBHOOK_SECRET is required for signed Stripe webhooks")

    def create_checkout_session(
        self,
        *,
        customer_account_id: str,
        amount_usd: float,
        success_url: str = "https://computemesh.inetconnector.com/docs?status=success",
        cancel_url: str = "https://computemesh.inetconnector.com/pricing?status=cancelled",
        currency: str = "usd",
    ) -> CheckoutSessionResult:
        self._require_live_configuration()
        if amount_usd < 5.0:
            raise StripeIntegrationError("Minimum deposit amount is $5.00")
        if amount_usd > 10_000.0:
            raise StripeIntegrationError("Maximum single deposit limit is $10,000.00")

        currency = currency.lower().strip()
        if currency != "usd":
            raise StripeIntegrationError("Only USD compute-credit deposits are currently supported")

        amount_cents = _amount_to_cents(amount_usd)
        amount_micro = _cents_to_micro_units(amount_cents)
        created_at = _utc_now()
        metadata = {
            "customer_account_id": customer_account_id,
            "amount_micro_units": str(amount_micro),
            "currency": currency,
            "product": "computemesh_prepaid_compute_credits",
        }
        product_data = {
            "name": "ComputeMesh prepaid compute credits",
            "metadata": metadata,
        }
        product_tax_code = os.environ.get("COMPUTEMESH_STRIPE_PRODUCT_TAX_CODE", "").strip()
        if product_tax_code:
            product_data["tax_code"] = product_tax_code

        params = {
            "mode": "payment",
            "success_url": success_url,
            "cancel_url": cancel_url,
            "client_reference_id": customer_account_id,
            "metadata": metadata,
            "payment_intent_data": {"metadata": metadata},
            "line_items": [
                {
                    "price_data": {
                        "currency": currency,
                        "unit_amount": amount_cents,
                        "product_data": product_data,
                    },
                    "quantity": 1,
                }
            ],
        }
        if os.environ.get("COMPUTEMESH_STRIPE_AUTOMATIC_TAX", "").strip() == "1":
            params["automatic_tax"] = {"enabled": True}

        try:
            session = self.stripe_client.checkout.Session.create(**params)
        except Exception as exc:
            raise StripeIntegrationError(f"Stripe Checkout Session creation failed: {exc}") from exc

        session_id = str(_stripe_get(session, "id", ""))
        checkout_url = str(_stripe_get(session, "url", ""))
        if not session_id or not checkout_url:
            raise StripeIntegrationError("Stripe did not return a Checkout Session id and URL")
        stripe_customer_id = str(_stripe_get(session, "customer", "") or "")
        payment_intent_id = str(_stripe_get(session, "payment_intent", "") or "")
        livemode = bool(_stripe_get(session, "livemode", False))

        if self.session_store:
            self.session_store.upsert(
                StripeSessionRecord(
                    session_id=session_id,
                    customer_account_id=customer_account_id,
                    amount_micro_units=amount_micro,
                    currency=currency,
                    checkout_url=checkout_url,
                    stripe_customer_id=stripe_customer_id,
                    payment_intent_id=payment_intent_id,
                    livemode=livemode,
                    status="created",
                    created_at=created_at,
                    updated_at=created_at,
                )
            )

        return CheckoutSessionResult(
            session_id=session_id,
            checkout_url=checkout_url,
            customer_account_id=customer_account_id,
            amount_usd=amount_usd,
            amount_micro_units=amount_micro,
            created_at=created_at,
            currency=currency,
            stripe_customer_id=stripe_customer_id,
            payment_intent_id=payment_intent_id,
            livemode=livemode,
        )

    def process_webhook_payload(
        self,
        *,
        raw_payload: bytes,
        signature_header: str | None,
    ) -> dict[str, Any]:
        """Verifies a Stripe webhook and deposits successful Checkout payments."""
        if not signature_header:
            raise StripeIntegrationError("Missing Stripe-Signature header")
        self._require_webhook_configuration()

        try:
            if self.webhook_verifier:
                payload = self.webhook_verifier(raw_payload, signature_header, self.webhook_secret)
            else:
                stripe = self.stripe_client or _load_stripe_module()
                payload = stripe.Webhook.construct_event(raw_payload, signature_header, self.webhook_secret)
        except Exception as exc:
            raise StripeIntegrationError(f"Stripe webhook signature verification failed: {exc}") from exc

        return self.process_webhook_event(payload=_stripe_to_plain(payload), trusted=True)

    def process_webhook_event(
        self,
        *,
        payload: dict[str, Any],
        trusted: bool = False,
    ) -> dict[str, Any]:
        """Deposits funds for an already verified Stripe event.

        Tests can call this with ``trusted=True`` after constructing a fixture.
        HTTP handlers must use ``process_webhook_payload`` so signature
        verification runs against the exact raw request body.
        """
        if not trusted:
            raise StripeIntegrationError("Stripe webhook events must be verified from the raw signed payload")

        event_type = str(payload.get("type", ""))
        event_id = str(payload.get("id", "") or "")
        if self.webhook_event_store:
            event_state = self.webhook_event_store.begin_webhook_event(
                event_id=event_id,
                event_type=event_type,
                payload=payload,
            )
            if event_state == "already_processed":
                return {"status": "already_processed", "stripe_event_id": event_id}

        def finish(result: dict[str, Any]) -> dict[str, Any]:
            if self.webhook_event_store:
                self.webhook_event_store.mark_webhook_processed(event_id)
            if event_id and "stripe_event_id" not in result:
                result["stripe_event_id"] = event_id
            return result

        try:
            data_object = payload.get("data", {}).get("object", {})

            if event_type not in ("checkout.session.completed", "checkout.session.async_payment_succeeded"):
                return finish({"status": "ignored", "reason": f"Unhandled event type: {event_type}"})

            session_id = data_object.get("id")
            if not session_id:
                raise StripeIntegrationError("Missing session ID in webhook payload")

            payment_status = str(data_object.get("payment_status", "paid") or "paid")
            if event_type == "checkout.session.completed" and payment_status not in ("paid", "no_payment_required"):
                return finish({
                    "status": "ignored",
                    "reason": f"Checkout Session {session_id} payment_status={payment_status}",
                })

            currency = str(data_object.get("currency", "usd") or "usd").lower()
            if currency != "usd":
                raise StripeIntegrationError(f"Unsupported Stripe Checkout currency for session {session_id}: {currency}")

            metadata = data_object.get("metadata", {})
            if not isinstance(metadata, dict):
                metadata = {}
            amount_micro = int(metadata.get("amount_micro_units", 0) or 0)
            customer_account_id = data_object.get("client_reference_id") or metadata.get("customer_account_id")
            stripe_customer_id = str(data_object.get("customer", "") or "")
            payment_intent_id = str(data_object.get("payment_intent", "") or "")
            livemode = bool(data_object.get("livemode", False))
            amount_subtotal_cents = int(data_object.get("amount_subtotal", 0) or 0)
            amount_total_cents = int(data_object.get("amount_total", 0) or 0)

            if not customer_account_id:
                cached = self.session_store.get(session_id) if self.session_store else None
                if cached:
                    customer_account_id = cached.customer_account_id
                    if amount_micro == 0:
                        amount_micro = cached.amount_micro_units

            cached = self.session_store.get(session_id) if self.session_store else None
            if cached:
                if cached.customer_account_id and customer_account_id and cached.customer_account_id != customer_account_id:
                    raise StripeIntegrationError(f"Session {session_id} customer mismatch")
                if cached.amount_micro_units and amount_micro and cached.amount_micro_units != amount_micro:
                    raise StripeIntegrationError(f"Session {session_id} amount mismatch")
                if not customer_account_id:
                    customer_account_id = cached.customer_account_id
                if amount_micro == 0:
                    amount_micro = cached.amount_micro_units
            elif amount_micro == 0:
                amount_micro = _cents_to_micro_units(amount_subtotal_cents or amount_total_cents)

            if amount_micro > 0:
                if amount_subtotal_cents and _cents_to_micro_units(amount_subtotal_cents) != amount_micro:
                    raise StripeIntegrationError(f"Session {session_id} amount mismatch")
                if amount_total_cents and _cents_to_micro_units(amount_total_cents) < amount_micro:
                    raise StripeIntegrationError(f"Session {session_id} total paid amount below credit amount")

            if not customer_account_id or amount_micro <= 0:
                raise StripeIntegrationError(f"Cannot resolve customer or deposit amount for session {session_id}")

            payment_reference = f"stripe_checkout:{session_id}"
            try:
                tx = self.ledger.deposit_customer_credits(
                    customer_account_id=customer_account_id,
                    amount_micro_units=amount_micro,
                    payment_reference=payment_reference,
                )
                if self.session_store:
                    self.session_store.mark_credited(
                        session_id=session_id,
                        transaction_id=tx.tx_id,
                        stripe_customer_id=stripe_customer_id,
                        payment_intent_id=payment_intent_id,
                        livemode=livemode,
                    )
                return finish({
                    "status": "credited",
                    "transaction_id": tx.tx_id,
                    "customer_account_id": customer_account_id,
                    "amount_usd": round(amount_micro / MICRO_UNIT_SCALE, 2),
                    "new_balance_usd": round(self.ledger.get_balance(customer_account_id) / MICRO_UNIT_SCALE, 2),
                    "stripe_session_id": session_id,
                    "payment_reference": payment_reference,
                })
            except DuplicateEventError:
                return finish({
                    "status": "already_processed",
                    "session_id": session_id,
                    "customer_account_id": customer_account_id,
                })
        except Exception as exc:
            if self.webhook_event_store:
                self.webhook_event_store.mark_webhook_failed(event_id, str(exc))
            raise
