"""Fail-closed gateway entry point for unified owner credits.

This migration target uses one durable owner ledger for purchased, promo and earned
credits, withdrawals, and protected-job escrow. Hardware-bound onboarding promo is
an explicit opt-in delegated to the private control plane before any signed grant
is accepted into the public journal.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from http import HTTPStatus
from http.server import ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

from services.billing.accounting import AccountingStore
from services.billing.confidential_owner_ledger import PayoutCapableConfidentialOwnerLedger
from services.billing.owner_accounts import OwnerAccountStore
from services.billing.owner_settlement import OwnerSettlementExecutor, PayoutCapableOwnerLedger
from services.billing.owner_settlement_runtime import RobustOwnerSettlementExecutor
from services.billing.stripe_connect import StripeConnectService
from services.common.config import CONFIG
from services.gateway.auth import GatewayAuthManager
from services.gateway.gpu_promo_dispatch_client import build_gpu_promo_dispatch_client_from_env
from services.gateway.inference_backend import build_inference_backend_from_env
from services.gateway.metrics_exporter import MetricsRegistry
from services.gateway.owner_inference import UnifiedOwnerInferenceEngine
from services.gateway.owner_promo_routes import (
    UnifiedOwnerPromoRoutes,
    build_signed_promo_applier_from_env,
)
from services.gateway.owner_provider_routes import UnifiedOwnerProviderRoutesHandler
from services.gateway.promo_control_plane import build_promo_control_plane_client_from_env
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
    return RobustOwnerSettlementExecutor(
        ledger=ledger,
        account_store=account_store,
        stripe_connect=StripeConnectService(
            stripe_api_key=os.environ.get("STRIPE_API_KEY", "").strip()
        ),
    )


def _build_owner_promo_routes(
    *,
    ledger: PayoutCapableOwnerLedger,
    owner_account_store: OwnerAccountStore,
    auth_manager: GatewayAuthManager,
) -> UnifiedOwnerPromoRoutes | None:
    if not _env_truthy("COMPUTEMESH_OWNER_PROMO_ONBOARDING"):
        return None
    gpu_dispatch = None
    if _env_truthy("COMPUTEMESH_OWNER_GPU_PROMO_SERVER_DRIVEN"):
        gpu_dispatch = build_gpu_promo_dispatch_client_from_env()
    return UnifiedOwnerPromoRoutes(
        owner_store=owner_account_store,
        ledger=ledger,
        auth_manager=auth_manager,
        control_plane=build_promo_control_plane_client_from_env(),
        applier=build_signed_promo_applier_from_env(
            owner_store=owner_account_store,
            ledger=ledger,
        ),
        gpu_dispatch=gpu_dispatch,
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

    ledger = PayoutCapableConfidentialOwnerLedger(storage_path=ledger_path)
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
    promo_routes = _build_owner_promo_routes(
        ledger=ledger,
        owner_account_store=owner_account_store,
        auth_manager=auth_manager,
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

        def _read_owner_action_body(self) -> dict | None:
            content_length_hdr = self.headers.get("Content-Length")
            if not content_length_hdr:
                self._send_error_response(
                    "Content-Length header required",
                    "invalid_request_error",
                    HTTPStatus.BAD_REQUEST,
                )
                return None
            try:
                content_length = int(content_length_hdr)
            except ValueError:
                self._send_error_response(
                    "Invalid Content-Length header",
                    "invalid_request_error",
                    HTTPStatus.BAD_REQUEST,
                )
                return None
            if content_length < 0 or content_length > MAX_REQUEST_PAYLOAD_BYTES:
                self._send_error_response(
                    f"Payload exceeds maximum allowed size ({MAX_REQUEST_PAYLOAD_BYTES} bytes)",
                    "payload_too_large",
                    HTTPStatus.REQUEST_ENTITY_TOO_LARGE,
                )
                return None
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
                return None
            return body

        def do_POST(self) -> None:
            clean_path = urlparse(self.path).path.rstrip("/")
            withdraw_paths = {"/v1/providers/withdraw", "/api/v1/providers/withdraw"}
            promo_challenge_paths = {
                "/v1/account/promo/challenge",
                "/api/v1/account/promo/challenge",
            }
            promo_verify_paths = {
                "/v1/account/promo/verify",
                "/api/v1/account/promo/verify",
            }
            gpu_onboard_paths = {
                "/v1/account/promo/gpu-onboard",
                "/api/v1/account/promo/gpu-onboard",
            }
            owner_paths = (
                withdraw_paths
                | promo_challenge_paths
                | promo_verify_paths
                | gpu_onboard_paths
            )
            if clean_path not in owner_paths:
                return super().do_POST()
            if not self._check_rate_limit():
                return

            body = self._read_owner_action_body()
            if body is None:
                return

            if clean_path in withdraw_paths:
                res, err, status = self.provider_routes.handle_withdraw(self.headers, body)
                error_type = "settlement_error"
            else:
                if self.promo_routes is None:
                    self._send_error_response(
                        "Owner promo onboarding is not enabled",
                        "promo_unavailable",
                        HTTPStatus.SERVICE_UNAVAILABLE,
                    )
                    return
                if clean_path in promo_challenge_paths:
                    res, err, status = self.promo_routes.handle_challenge(self.headers, body)
                elif clean_path in promo_verify_paths:
                    res, err, status = self.promo_routes.handle_verify(self.headers, body)
                else:
                    res, err, status = self.promo_routes.handle_gpu_onboard(self.headers, body)
                error_type = "promo_error"

            if err:
                self._send_error_response(err, error_type, status)
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
    UnifiedOwnerGatewayHandler.promo_routes = promo_routes
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
        cls.promo_routes = _build_owner_promo_routes(
            ledger=cls.ledger,
            owner_account_store=cls.owner_account_store,
            auth_manager=cls.auth_manager,
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
