"""Fail-closed gateway entry point for unified owner credits.

The legacy ``services.gateway.server`` remains unchanged and is still the default.
This explicit migration target requires durable owner/billing storage and enables
owner-scoped Stripe Connect settlement only for withdrawable ``earned`` credits.
"""
from __future__ import annotations

import argparse
from http import HTTPStatus
from http.server import ThreadingHTTPServer
import json
import os
from pathlib import Path
import sys
from urllib.parse import urlparse

from services.billing.accounting import AccountingStore
from services.billing.owner_accounts import OwnerAccountStore
from services.billing.owner_settlement import OwnerSettlementExecutor, PayoutCapableOwnerLedger
from services.billing.stripe_connect import StripeConnectService
from services.common.config import CONFIG
from services.gateway.auth import GatewayAuthManager
from services.gateway.inference_backend import build_inference_backend_from_env
from services.gateway.metrics_exporter import MetricsRegistry
from services.gateway.owner_inference import UnifiedOwnerInferenceEngine
from services.gateway.owner_provider_routes import UnifiedOwnerProviderRoutesHandler
from services.gateway.routes_billing import BillingRoutesHandler
from services.gateway.security import MAX_REQUEST_PAYLOAD_BYTES
from services.gateway.server import DEFAULT_PORT, GatewayHandler, _build_stripe_service
from services.gateway.teaser import TeaserQuotaManager


def _env_truthy(name: str) -> bool:
    return os.environ.get(name, "").strip().lower() in {"1", "true", "yes", "on"}


def _required_path(name: str) -> Path:
    raw = os.environ.get(name, "").strip()
    if not raw:
        raise RuntimeError(f"{name} is required for unified owner gateway mode")
    return Path(raw)


def _build_owner_settlement_executor(
    *,
    ledger: PayoutCapableOwnerLedger,
    account_store: AccountingStore,
) -> OwnerSettlementExecutor:
    return OwnerSettlementExecutor(
        ledger=ledger,
        account_store=account_store,
        stripe_connect=StripeConnectService(
            stripe_api_key=os.environ.get("STRIPE_API_KEY", "").strip()
        ),
    )


def build_unified_owner_handler() -> type[GatewayHandler]:
    """Build an isolated GatewayHandler subclass with unified owner state."""
    if not _env_truthy("COMPUTEMESH_UNIFIED_OWNER_CREDITS"):
        raise RuntimeError(
            "Unified owner gateway is disabled; set COMPUTEMESH_UNIFIED_OWNER_CREDITS=1 explicitly"
        )

    ledger_path = _required_path("COMPUTEMESH_LEDGER_PATH")
    owner_db_path = _required_path("COMPUTEMESH_OWNER_ACCOUNT_DB_PATH")
    accounting_db_path = _required_path("COMPUTEMESH_ACCOUNTING_DB_PATH")

    ledger = PayoutCapableOwnerLedger(storage_path=ledger_path)
    owner_account_store = OwnerAccountStore(owner_db_path)
    account_store = AccountingStore(accounting_db_path)

    stripe_svc = _build_stripe_service(ledger, account_store)
    settlement_executor = _build_owner_settlement_executor(
        ledger=ledger,
        account_store=account_store,
    )
    metrics = MetricsRegistry()
    teaser_manager = TeaserQuotaManager(
        max_requests=CONFIG.teaser.max_free_requests,
        max_tokens=CONFIG.teaser.max_free_tokens,
        window_seconds=CONFIG.teaser.window_seconds,
    )
    auth_manager = GatewayAuthManager(
        ledger=ledger,
        teaser_manager=teaser_manager,
        owner_account_store=owner_account_store,
    )
    billing_routes = BillingRoutesHandler(
        ledger=ledger,
        stripe_svc=stripe_svc,
        auth_manager=auth_manager,
    )
    provider_routes = UnifiedOwnerProviderRoutesHandler(
        owner_account_store=owner_account_store,
        account_store=account_store,
        settlement_executor=settlement_executor,
        auth_manager=auth_manager,
        ledger=ledger,
    )
    inference_engine = UnifiedOwnerInferenceEngine(
        ledger=ledger,
        owner_account_store=owner_account_store,
        metrics=metrics,
        teaser_manager=teaser_manager,
        backend=build_inference_backend_from_env(),
    )

    class UnifiedOwnerGatewayHandler(GatewayHandler):
        """Gateway handler bound to unified owner accounting and settlement."""

        def do_POST(self) -> None:
            clean_path = urlparse(self.path).path.rstrip("/")
            if clean_path not in {"/v1/providers/withdraw", "/api/v1/providers/withdraw"}:
                return super().do_POST()
            if not self._check_rate_limit():
                return

            content_length_hdr = self.headers.get("Content-Length")
            if not content_length_hdr:
                self._send_error_response(
                    "Content-Length header required",
                    "invalid_request_error",
                    HTTPStatus.BAD_REQUEST,
                )
                return
            try:
                content_length = int(content_length_hdr)
            except ValueError:
                self._send_error_response(
                    "Invalid Content-Length header",
                    "invalid_request_error",
                    HTTPStatus.BAD_REQUEST,
                )
                return
            if content_length > MAX_REQUEST_PAYLOAD_BYTES:
                self._send_error_response(
                    f"Payload exceeds maximum allowed size ({MAX_REQUEST_PAYLOAD_BYTES} bytes)",
                    "payload_too_large",
                    HTTPStatus.REQUEST_ENTITY_TOO_LARGE,
                )
                return
            try:
                raw_body = self.rfile.read(content_length)
                body = json.loads(raw_body.decode("utf-8")) if raw_body else {}
                if not isinstance(body, dict):
                    raise ValueError("request body must be a JSON object")
            except Exception:
                self._send_error_response(
                    "Malformed JSON request body",
                    "invalid_request_error",
                    HTTPStatus.BAD_REQUEST,
                )
                return

            res, err, status = self.provider_routes.handle_withdraw(self.headers, body)
            if err:
                self._send_error_response(err, "settlement_error", status)
            else:
                self._send_json(res or {}, status)

    UnifiedOwnerGatewayHandler.ledger = ledger
    UnifiedOwnerGatewayHandler.owner_account_store = owner_account_store
    UnifiedOwnerGatewayHandler.account_store = account_store
    UnifiedOwnerGatewayHandler.stripe_svc = stripe_svc
    UnifiedOwnerGatewayHandler.settlement_executor = settlement_executor
    UnifiedOwnerGatewayHandler.metrics = metrics
    UnifiedOwnerGatewayHandler.teaser_manager = teaser_manager
    UnifiedOwnerGatewayHandler.auth_manager = auth_manager
    UnifiedOwnerGatewayHandler.billing_routes = billing_routes
    UnifiedOwnerGatewayHandler.provider_routes = provider_routes
    UnifiedOwnerGatewayHandler.inference_engine = inference_engine

    @classmethod
    def sync_subsystems(cls) -> None:
        """Rebuild owner-aware subhandlers after tests/operator dependency injection."""
        backend = getattr(getattr(cls, "inference_engine", None), "backend", None)
        cls.auth_manager = GatewayAuthManager(
            ledger=cls.ledger,
            teaser_manager=cls.teaser_manager,
            api_keys=getattr(cls, "api_keys", {}),
            owner_account_store=cls.owner_account_store,
        )
        cls.billing_routes = BillingRoutesHandler(
            ledger=cls.ledger,
            stripe_svc=cls.stripe_svc,
            auth_manager=cls.auth_manager,
        )
        cls.settlement_executor = _build_owner_settlement_executor(
            ledger=cls.ledger,
            account_store=cls.account_store,
        )
        cls.provider_routes = UnifiedOwnerProviderRoutesHandler(
            owner_account_store=cls.owner_account_store,
            account_store=cls.account_store,
            settlement_executor=cls.settlement_executor,
            auth_manager=cls.auth_manager,
            ledger=cls.ledger,
        )
        cls.inference_engine = UnifiedOwnerInferenceEngine(
            ledger=cls.ledger,
            owner_account_store=cls.owner_account_store,
            metrics=cls.metrics,
            teaser_manager=cls.teaser_manager,
            backend=backend,
        )

    UnifiedOwnerGatewayHandler.sync_subsystems = sync_subsystems
    return UnifiedOwnerGatewayHandler


def create_unified_owner_gateway_server(
    host: str = "127.0.0.1",
    port: int = 0,
) -> tuple[ThreadingHTTPServer, int]:
    handler = build_unified_owner_handler()
    server = ThreadingHTTPServer((host, port), handler)
    return server, int(server.server_address[1])


def run_unified_owner_gateway_server(
    host: str = "0.0.0.0",
    port: int = DEFAULT_PORT,
) -> None:
    server, bound_port = create_unified_owner_gateway_server(host, port)
    print(f"ComputeMesh Unified Owner Gateway listening on http://{host}:{bound_port}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nShutting down Unified Owner Gateway...")
    finally:
        server.server_close()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="ComputeMesh Gateway with unified owner credits"
    )
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    args = parser.parse_args(argv)
    run_unified_owner_gateway_server(args.host, args.port)
    return 0


if __name__ == "__main__":
    sys.exit(main())
