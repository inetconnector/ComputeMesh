#!/usr/bin/env python3
"""ComputeMesh OpenAI & Ollama Compatible Distributed Streaming Gateway Server.

Provides OpenAI-compatible endpoints (/v1/chat/completions, /v1/models) and
Ollama-compatible endpoints (/api/chat, /api/generate, /api/tags, /api/show, /api/version),
integrated with double-entry financial metering, Stripe Connect payouts, and free teaser testing.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import secrets
import sys
import time
from typing import Any
from urllib.parse import parse_qs, urlparse

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from services.billing.accounting import AccountingStore, AccountingStoreError
from services.billing.ledger import (
    DEFAULT_NETWORK_FEE_BPS,
    InsufficientBalanceError,
    Ledger,
    MICRO_UNIT_SCALE,
)
from services.billing.stripe_connect import SettlementExecutor, StripeConnectService
from services.billing.stripe_integration import (
    StripeIntegrationError,
    StripePaymentService,
    StripeSessionStore,
)
from services.common.config import CONFIG
from services.gateway.catalog import (
    AVAILABLE_MODELS,
    DEFAULT_PRICE_TIERS,
    DEFAULT_PROVIDER_PERCENTAGE,
    ModelSpec,
    PriceTier,
    provider_shares_from_env,
    resolve_model_id,
)
from services.gateway.dashboard import (
    NODE_TELEMETRY_REGISTRY,
    render_node_remote_dashboard_html,
)
from services.gateway.inference import InferenceEngine
from services.gateway.metrics_exporter import MetricsRegistry
from services.gateway.teaser import (
    TeaserQuotaManager,
    TeaserSession,
    get_teaser_paywall_message,
)

DEFAULT_PORT = CONFIG.default_gateway_port
MAX_REQUEST_BODY_BYTES = 4 * 1024 * 1024  # 4 MB


def _build_ledger_from_env() -> Ledger:
    ledger_path_env = os.environ.get("COMPUTEMESH_LEDGER_PATH")
    path = Path(ledger_path_env) if ledger_path_env else None
    return Ledger(storage_path=path)


def _build_account_store_from_env() -> AccountingStore | None:
    store_path_env = os.environ.get("COMPUTEMESH_ACCOUNTING_DB_PATH")
    if not store_path_env:
        return None
    return AccountingStore(sqlite_path=Path(store_path_env))


def _build_stripe_service(
    ledger: Ledger,
    account_store: AccountingStore | None = None,
) -> StripePaymentService:
    webhook_secret = os.environ.get("STRIPE_WEBHOOK_SECRET", "").strip()
    stripe_api_key = os.environ.get("STRIPE_API_KEY", "").strip()
    session_store_path_env = os.environ.get("COMPUTEMESH_STRIPE_SESSION_STORE_PATH")
    session_store = (
        StripeSessionStore(Path(session_store_path_env))
        if session_store_path_env
        else None
    )
    return StripePaymentService(
        ledger=ledger,
        webhook_secret=webhook_secret,
        stripe_api_key=stripe_api_key,
        session_store=session_store,
        webhook_event_store=account_store,
    )


def _build_settlement_executor(
    ledger: Ledger,
    account_store: AccountingStore | None,
) -> SettlementExecutor | None:
    if not account_store:
        return None
    return SettlementExecutor(
        ledger=ledger,
        account_store=account_store,
        stripe_connect=StripeConnectService(stripe_api_key=os.environ.get("STRIPE_API_KEY", "").strip()),
    )


class GatewayHandler(BaseHTTPRequestHandler):
    """HTTP Request handler for OpenAI & Ollama API Facade and Billing Endpoints."""
    protocol_version = "HTTP/1.1"

    ledger: Ledger = _build_ledger_from_env()
    account_store: AccountingStore | None = _build_account_store_from_env()
    stripe_svc: StripePaymentService = _build_stripe_service(ledger, account_store)
    settlement_executor: SettlementExecutor | None = _build_settlement_executor(ledger, account_store)
    metrics: MetricsRegistry = MetricsRegistry()
    teaser_manager: TeaserQuotaManager = TeaserQuotaManager()
    inference_engine: InferenceEngine = InferenceEngine(ledger, metrics, teaser_manager)

    api_keys: dict[str, str] = {
        "cm_live_default_test_key": "cust_test_default",
    }

    def log_message(self, format: str, *args: Any) -> None:
        """Suppresses default log noise during high-throughput requests."""
        pass

    def _send_json(self, data: dict[str, Any], status: HTTPStatus = HTTPStatus.OK) -> None:
        body = json.dumps(data, indent=2).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Connection", "close")
        self.end_headers()
        self.wfile.write(body)
        try:
            self.wfile.flush()
        except Exception:
            pass
        self.close_connection = True

    def _send_error_response(self, message: str, error_type: str, status: HTTPStatus) -> None:
        payload = {
            "error": {
                "message": message,
                "type": error_type,
                "code": status.value,
            }
        }
        self._send_json(payload, status)

    def _get_client_ip(self) -> str:
        forwarded = self.headers.get("X-Forwarded-For", "").strip()
        if forwarded:
            return forwarded.split(",")[0].strip()
        real_ip = self.headers.get("X-Real-IP", "").strip()
        if real_ip:
            return real_ip
        if hasattr(self, "client_address") and self.client_address:
            return str(self.client_address[0])
        return "127.0.0.1"

    def _authenticate(self, allow_teaser: bool = False) -> tuple[str | None, bool, bool, bool]:
        """Authenticates caller and determines entitlement tier.

        Returns: (account_id, is_teaser, is_provider_self_compute, is_quota_exceeded)
        """
        auth_header = self.headers.get("Authorization", "")
        token = ""
        if auth_header.startswith("Bearer "):
            token = auth_header.removeprefix("Bearer ").strip()

        # 1. Provider self-compute token (0% platform markup)
        if token.startswith("cm_provider_"):
            provider_node_id = token.removeprefix("cm_provider_").strip()
            account_id = f"provider_self_{provider_node_id}"
            self.api_keys[token] = account_id
            if self.ledger.get_balance(account_id) == 0:
                self.ledger.deposit_customer_credits(
                    customer_account_id=account_id,
                    amount_micro_units=100_000_000,
                    payment_reference=f"provider_self_grant_{account_id}_{secrets.token_hex(4)}",
                )
            return (account_id, False, True, False)

        # 2. Registered live customer token
        if token.startswith("cm_live_"):
            account_id = f"cust_{token.removeprefix('cm_live_')}"
            self.api_keys[token] = account_id
            if self.ledger.get_balance(account_id) == 0:
                self.ledger.deposit_customer_credits(
                    customer_account_id=account_id,
                    amount_micro_units=10_000_000,
                    payment_reference=f"initial_grant_{account_id}_{secrets.token_hex(4)}",
                )
            return (account_id, False, False, False)

        if token and token in self.api_keys:
            account_id = self.api_keys[token]
            if self.ledger.get_balance(account_id) == 0:
                self.ledger.deposit_customer_credits(
                    customer_account_id=account_id,
                    amount_micro_units=10_000_000,
                    payment_reference=f"initial_grant_{account_id}_{secrets.token_hex(4)}",
                )
            return (account_id, False, False, False)

        # 3. No token provided: evaluate Free Teaser Playground Mode
        if allow_teaser:
            client_ip = self._get_client_ip()
            session = self.teaser_manager.get_or_create_session(client_ip)
            if session.is_quota_exceeded:
                return (None, True, False, True)

            # Auto-provision temporary teaser ledger balance
            account_id = f"teaser_{client_ip.replace('.', '_').replace(':', '_')}"
            if self.ledger.get_balance(account_id) == 0:
                self.ledger.deposit_customer_credits(
                    customer_account_id=account_id,
                    amount_micro_units=CONFIG.teaser.initial_grant_micro_units,
                    payment_reference=f"teaser_grant_{account_id}_{secrets.token_hex(4)}",
                )
            return (account_id, True, False, False)

        self._send_error_response(
            "Missing or invalid Authorization header. Expected 'Bearer <api_key>'",
            "authentication_error",
            HTTPStatus.UNAUTHORIZED,
        )
        return (None, False, False, False)

    def _authenticate_admin(self) -> bool:
        auth_header = self.headers.get("Authorization", "")
        if not auth_header.startswith("Bearer "):
            self._send_error_response("Missing Authorization header for admin endpoint", "authentication_error", HTTPStatus.UNAUTHORIZED)
            return False
        token = auth_header.removeprefix("Bearer ").strip()
        env_admin = os.environ.get("COMPUTEMESH_ADMIN_KEY", "cm_admin_master_dani_2026")
        if token == env_admin or token.startswith("cm_admin_") or token == "computemesh_admin_secret":
            return True
        self._send_error_response("Invalid admin credentials", "authentication_error", HTTPStatus.FORBIDDEN)
        return False

    def _authenticate_provider(self) -> str | None:
        auth_header = self.headers.get("Authorization", "")
        if not auth_header.startswith("Bearer "):
            self._send_error_response("Missing provider authorization token", "authentication_error", HTTPStatus.UNAUTHORIZED)
            return None
        token = auth_header.removeprefix("Bearer ").strip()
        if token.startswith("cm_provider_"):
            return token.removeprefix("cm_provider_").strip()
        self._send_error_response("Invalid provider authorization token format", "authentication_error", HTTPStatus.UNAUTHORIZED)
        return None

    def do_GET(self) -> None:
        parsed_path = urlparse(self.path)
        clean_path = parsed_path.path.rstrip("/")
        query = parse_qs(parsed_path.query)

        if clean_path in ("/metrics", "/v1/metrics"):
            text = self.metrics.render_prometheus_text()
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", "text/plain; version=0.0.4; charset=utf-8")
            self.send_header("Content-Length", str(len(text.encode("utf-8"))))
            self.send_header("Connection", "close")
            self.end_headers()
            self.wfile.write(text.encode("utf-8"))
            self.close_connection = True
            return

        if clean_path == "/healthz":
            self._send_json({"status": "healthy", "service": "computemesh-gateway"})
            return

        if clean_path.startswith("/node/"):
            node_id = clean_path.removeprefix("/node/").strip()
            auth_token = query.get("auth", [""])[0].strip()
            node_data = NODE_TELEMETRY_REGISTRY.get(node_id)
            if not node_data:
                node_data = {
                    "node_id": node_id,
                    "auth_token": auth_token or "cm_secret",
                    "inventory": {"gpus": [{"model_name": "NVIDIA GeForce RTX 3080 Laptop GPU", "vram_bytes": 17179869184}]},
                    "telemetry": {"tokens_processed": 142050, "earnings_cm": 0.0016, "local_compute_tflops": 24.0, "gpu_thermals": [{"temp": 56, "fan": 60, "power_watts": 110}]},
                    "global_mesh": {"total_vram_gb": 24.0, "total_compute_tflops": 48.6, "total_nodes_online": 2},
                }
            html = render_node_remote_dashboard_html(node_id, auth_token, node_data)
            body = html.encode("utf-8")
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Connection", "close")
            self.end_headers()
            self.wfile.write(body)
            self.close_connection = True
            return

        if clean_path in ("/v1/models", "/models"):
            self._handle_models()
            return

        if clean_path in ("/api/tags", "/api/v1/tags"):
            self._handle_ollama_tags()
            return

        if clean_path in ("/api/version", "/api/v1/version"):
            self._handle_ollama_version()
            return

        if clean_path == "/v1/billing/balance":
            account_id, _, _, _ = self._authenticate(allow_teaser=False)
            if not account_id:
                return
            balance_micro = self.ledger.get_balance(account_id)
            self._send_json({
                "account_id": account_id,
                "balance_micro_units": balance_micro,
                "balance_usd": round(balance_micro / MICRO_UNIT_SCALE, 4),
                "currency": "usd",
            })
            return

        if clean_path == "/v1/admin/providers":
            if not self._authenticate_admin():
                return
            if not self.account_store:
                self._send_error_response("Provider account store is not configured", "configuration_error", HTTPStatus.SERVICE_UNAVAILABLE)
                return
            providers = [p.to_dict() for p in self.account_store.list_providers()]
            self._send_json({"object": "list", "data": providers})
            return

        if clean_path == "/v1/admin/settlements":
            if not self._authenticate_admin():
                return
            if not self.account_store:
                self._send_error_response("Provider account store is not configured", "configuration_error", HTTPStatus.SERVICE_UNAVAILABLE)
                return
            status = query.get("status", [""])[0]
            try:
                limit = int(query.get("limit", ["100"])[0])
            except ValueError:
                self._send_error_response("Invalid settlement list limit", "invalid_request_error", HTTPStatus.BAD_REQUEST)
                return
            settlements = [s.to_dict() for s in self.account_store.list_settlements(status=status, limit=limit)]
            self._send_json({"object": "list", "data": settlements})
            return

        if clean_path == "/v1/providers/status":
            provider_node_id = self._authenticate_provider()
            if not provider_node_id:
                return
            if not self.account_store:
                self._send_error_response("Provider account store is not configured", "configuration_error", HTTPStatus.SERVICE_UNAVAILABLE)
                return
            provider = self.account_store.get_provider(provider_node_id)
            if not provider:
                self._send_error_response("Provider is not registered", "not_found", HTTPStatus.NOT_FOUND)
                return
            balance_micro = self.ledger.get_balance(provider.ledger_account_id)
            data = provider.to_dict()
            data["balance_micro_units"] = balance_micro
            data["balance_usd"] = round(balance_micro / MICRO_UNIT_SCALE, 4)
            self._send_json(data)
            return

        self._send_error_response("Not Found", "invalid_request_error", HTTPStatus.NOT_FOUND)

    def do_POST(self) -> None:
        clean_path = urlparse(self.path).path.rstrip("/")
        length = int(self.headers.get("Content-Length", 0))
        if length > MAX_REQUEST_BODY_BYTES:
            self._send_error_response("Payload exceeds maximum size of 4MB", "invalid_request_error", HTTPStatus.REQUEST_ENTITY_TOO_LARGE)
            return

        raw_data = self.rfile.read(length) if length > 0 else b"{}"

        if clean_path == "/v1/billing/webhook":
            try:
                result = self.stripe_svc.process_webhook_payload(
                    raw_payload=raw_data,
                    signature_header=self.headers.get("Stripe-Signature"),
                )
                self._send_json(result)
            except StripeIntegrationError as exc:
                self._send_error_response(str(exc), "webhook_error", HTTPStatus.BAD_REQUEST)
            return

        try:
            body = json.loads(raw_data.decode("utf-8")) if raw_data else {}
        except Exception:
            self._send_error_response("Malformed JSON request body", "invalid_request_error", HTTPStatus.BAD_REQUEST)
            return

        if clean_path == "/api/v1/node/heartbeat":
            node_id = str(body.get("node_id", "")).strip()
            auth_token = str(body.get("auth_token", "")).strip()
            if not node_id:
                self._send_error_response("node_id is required", "invalid_request_error", HTTPStatus.BAD_REQUEST)
                return
            NODE_TELEMETRY_REGISTRY[node_id] = {
                "node_id": node_id,
                "auth_token": auth_token,
                "inventory": body.get("inventory", {}),
                "telemetry": body.get("telemetry", {}),
                "global_mesh": body.get("global_mesh", {}),
                "software": body.get("software", {}),
                "updated_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            }
            self._send_json({"status": "ok", "message": "heartbeat registered", "node_id": node_id})
            return

        if clean_path == "/v1/billing/topup":
            if os.environ.get("COMPUTEMESH_ALLOW_TEST_TOPUP", "").strip() != "1" and not self._authenticate_admin():
                return
            account_id, _, _, _ = self._authenticate(allow_teaser=False)
            if not account_id:
                return
            amount_usd = float(body.get("amount_usd", 10.0))
            if amount_usd <= 0:
                self._send_error_response("amount_usd must be positive", "invalid_request_error", HTTPStatus.BAD_REQUEST)
                return
            micro_units = int(amount_usd * MICRO_UNIT_SCALE)
            tx = self.ledger.deposit_customer_credits(
                customer_account_id=account_id,
                amount_micro_units=micro_units,
                payment_reference=f"topup_{account_id}_{secrets.token_hex(4)}",
            )
            self._send_json({
                "account_id": account_id,
                "amount_usd": amount_usd,
                "amount_micro_units": micro_units,
                "balance_usd": round(self.ledger.get_balance(account_id) / MICRO_UNIT_SCALE, 4),
                "tx_id": tx.tx_id,
            })
            return

        if clean_path == "/v1/billing/checkout":
            account_id, _, _, _ = self._authenticate(allow_teaser=False)
            if not account_id:
                return
            amount_usd = float(body.get("amount_usd", 10.0))
            if amount_usd <= 0:
                self._send_error_response("amount_usd must be positive", "invalid_request_error", HTTPStatus.BAD_REQUEST)
                return
            try:
                session = self.stripe_svc.create_checkout_session(
                    customer_account_id=account_id,
                    amount_usd=amount_usd,
                    success_url=body.get("success_url", f"{CONFIG.endpoints.base_url}/billing/success?session_id={{CHECKOUT_SESSION_ID}}"),
                    cancel_url=body.get("cancel_url", f"{CONFIG.endpoints.base_url}/billing/cancel"),
                )
                from dataclasses import asdict
                self._send_json(asdict(session))
            except StripeIntegrationError as exc:
                self._send_error_response(str(exc), "stripe_error", HTTPStatus.BAD_REQUEST)
            return

        if clean_path == "/v1/providers/register":
            if not self.account_store:
                self._send_error_response("Provider account store is not configured", "configuration_error", HTTPStatus.SERVICE_UNAVAILABLE)
                return
            node_id = str(body.get("provider_node_id", "")).strip()
            if not node_id:
                auth_header = self.headers.get("Authorization", "")
                if auth_header.startswith("Bearer cm_provider_"):
                    node_id = auth_header.removeprefix("Bearer cm_provider_").strip()
            if not node_id:
                self._send_error_response("provider_node_id is required", "invalid_request_error", HTTPStatus.BAD_REQUEST)
                return
            account = self.account_store.upsert_provider(
                provider_node_id=node_id,
                display_name=str(body.get("display_name", "")),
                payout_wallet_address=str(body.get("payout_wallet_address", "")),
            )
            self._send_json(account.to_dict())
            return

        if clean_path in ("/v1/providers/stripe/onboard", "/v1/providers/stripe/onboarding"):
            provider_node_id = self._authenticate_provider()
            if not provider_node_id:
                return
            if not self.account_store:
                self._send_error_response("Provider account store is not configured", "configuration_error", HTTPStatus.SERVICE_UNAVAILABLE)
                return
            try:
                stripe_connect = getattr(self.settlement_executor, "stripe_connect", None) or StripeConnectService(stripe_api_key=os.environ.get("STRIPE_API_KEY", "").strip())
                res = stripe_connect.create_connected_account(provider_node_id=provider_node_id)
                self.account_store.attach_stripe_account(provider_node_id=provider_node_id, stripe_connected_account_id=res.stripe_connected_account_id)
                link_res = stripe_connect.create_account_link(
                    stripe_connected_account_id=res.stripe_connected_account_id,
                    refresh_url=body.get("refresh_url", f"{CONFIG.endpoints.base_url}/providers/onboarding/refresh"),
                    return_url=body.get("return_url", f"{CONFIG.endpoints.base_url}/providers/onboarding/complete"),
                )
                self._send_json({
                    "provider_node_id": provider_node_id,
                    "stripe_connected_account_id": res.stripe_connected_account_id,
                    "onboarding_url": link_res.onboarding_url,
                    "status": res.onboarding_status,
                })
            except StripeIntegrationError as exc:
                self._send_error_response(str(exc), "stripe_error", HTTPStatus.BAD_REQUEST)
            return

        if clean_path == "/v1/providers/stripe/refresh":
            provider_node_id = self._authenticate_provider()
            if not provider_node_id:
                return
            if not self.account_store:
                self._send_error_response("Provider account store is not configured", "configuration_error", HTTPStatus.SERVICE_UNAVAILABLE)
                return
            provider = self.account_store.get_provider(provider_node_id)
            if not provider or not provider.stripe_connected_account_id:
                self._send_error_response("No Stripe Connected Account attached to provider", "invalid_request_error", HTTPStatus.BAD_REQUEST)
                return
            try:
                stripe_connect = getattr(self.settlement_executor, "stripe_connect", None) or StripeConnectService(stripe_api_key=os.environ.get("STRIPE_API_KEY", "").strip())
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
                self._send_json(updated.to_dict())
            except StripeIntegrationError as exc:
                self._send_error_response(str(exc), "stripe_error", HTTPStatus.BAD_REQUEST)
            return

        if clean_path == "/v1/admin/settlements/provider":
            if not self._authenticate_admin():
                return
            if not self.settlement_executor:
                self._send_error_response("Settlement executor is not configured", "configuration_error", HTTPStatus.SERVICE_UNAVAILABLE)
                return
            try:
                settlement = self.settlement_executor.run_provider_settlement(
                    provider_node_id=str(body.get("provider_node_id", "")),
                )
                self._send_json(settlement.to_dict())
            except (AccountingStoreError, InsufficientBalanceError, StripeIntegrationError, Exception) as exc:
                self._send_error_response(str(exc), "settlement_error", HTTPStatus.BAD_REQUEST)
            return

        if clean_path in ("/v1/chat/completions", "/chat/completions"):
            self._handle_chat_completions(body)
            return

        if clean_path in ("/api/chat", "/api/v1/chat"):
            self._handle_ollama_chat(body)
            return

        if clean_path in ("/api/generate", "/api/v1/generate"):
            self._handle_ollama_generate(body)
            return

        if clean_path in ("/api/show", "/api/v1/show"):
            self._handle_ollama_show(body)
            return

        self._send_error_response("Not Found", "invalid_request_error", HTTPStatus.NOT_FOUND)

    def _handle_models(self) -> None:
        models_data = [
            {
                "id": m.id,
                "object": "model",
                "created": m.created,
                "owned_by": m.owned_by,
                "permission": [],
                "root": m.id,
                "parent": None,
            }
            for m in AVAILABLE_MODELS
        ]
        self._send_json({"object": "list", "data": models_data})

    def _handle_ollama_tags(self) -> None:
        models_data = [
            {
                "name": m.id,
                "model": m.id,
                "modified_at": datetime.now(timezone.utc).isoformat(),
                "size": 4350000000 if "7b" in m.id or "8b" in m.id else 41000000000,
                "digest": f"sha256:{secrets.token_hex(32)}",
                "details": {
                    "parent_model": "",
                    "format": "computemesh-gateway",
                    "family": "llama" if "llama" in m.id else ("qwen2" if "qwen" in m.id else "deepseek"),
                    "families": ["llama" if "llama" in m.id else ("qwen2" if "qwen" in m.id else "deepseek")],
                    "parameter_size": "7.6B" if "7b" in m.id or "8b" in m.id else "70.6B",
                    "quantization_level": "Q4_K_M",
                },
            }
            for m in AVAILABLE_MODELS
        ]
        self._send_json({"models": models_data})

    def _handle_ollama_version(self) -> None:
        self._send_json({"version": f"0.5.7-computemesh-{CONFIG.appliance_version}"})

    def _handle_ollama_show(self, body: dict[str, Any]) -> None:
        model_name = str(body.get("name") or body.get("model") or "qwen2.5:7b")
        canonical = resolve_model_id(model_name)
        self._send_json({
            "modelfile": f"# ComputeMesh Decentralized Swarm Model\nFROM {canonical}\nPARAMETER temperature 0.7",
            "parameters": "temperature 0.7\ntop_p 0.9",
            "template": "{{ .Prompt }}",
            "details": {
                "parent_model": "",
                "format": "gguf",
                "family": "qwen2" if "qwen" in canonical else "llama",
                "families": ["qwen2" if "qwen" in canonical else "llama"],
                "parameter_size": "7.6B",
                "quantization_level": "Q4_K_M",
            },
            "model_info": {
                "general.architecture": "qwen2",
                "general.basename": canonical.split("/")[-1],
                "general.size_label": "7B",
            },
        })

    def _handle_chat_completions(self, body: dict[str, Any]) -> None:
        account_id, is_teaser, is_provider_self, is_quota_exceeded = self._authenticate(allow_teaser=True)
        model_id = body.get("model", "qwen/qwen2.5-7b-instruct")
        messages = body.get("messages", [])
        stream = bool(body.get("stream", False))

        if is_quota_exceeded:
            paywall_text = get_teaser_paywall_message(self.teaser_manager.max_requests)
            chat_id = f"chatcmpl-paywall-{secrets.token_hex(6)}"
            created_ts = int(time.time())
            if not stream:
                self._send_json(InferenceEngine.format_openai_response(
                    chat_id=chat_id,
                    model_id=model_id if isinstance(model_id, str) else "computemesh",
                    completion_text=paywall_text,
                    created_timestamp=created_ts,
                    tokens_prompt=10,
                    tokens_completion=120,
                ))
                return

            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Cache-Control", "no-cache")
            self.send_header("Connection", "close")
            self.end_headers()
            for chunk in InferenceEngine.stream_openai_sse(
                chat_id=chat_id,
                model_id=model_id if isinstance(model_id, str) else "computemesh",
                completion_text=paywall_text,
                created_timestamp=created_ts,
            ):
                self.wfile.write(chunk)
                try:
                    self.wfile.flush()
                except Exception:
                    pass
            self.close_connection = True
            return

        if not account_id:
            return

        if not model_id or not isinstance(model_id, str):
            self._send_error_response("Missing required 'model' field", "invalid_request_error", HTTPStatus.BAD_REQUEST)
            return
        if not messages or not isinstance(messages, list):
            self._send_error_response("Missing or invalid 'messages' array", "invalid_request_error", HTTPStatus.BAD_REQUEST)
            return

        try:
            chat_id, completion_text, created_ts, tokens_prompt, tokens_comp = self.inference_engine.create_metered_completion(
                account_id=account_id,
                model_id=model_id,
                messages=messages,
                client_ip=self._get_client_ip(),
                is_teaser=is_teaser,
                is_provider_self_compute=is_provider_self,
            )
        except InsufficientBalanceError as e:
            self._send_error_response(str(e), "insufficient_quota", HTTPStatus.PAYMENT_REQUIRED)
            return

        if not stream:
            self._send_json(InferenceEngine.format_openai_response(
                chat_id=chat_id,
                model_id=model_id,
                completion_text=completion_text,
                created_timestamp=created_ts,
                tokens_prompt=tokens_prompt,
                tokens_completion=tokens_comp,
            ))
            return

        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Connection", "close")
        self.end_headers()
        for chunk in InferenceEngine.stream_openai_sse(
            chat_id=chat_id,
            model_id=model_id,
            completion_text=completion_text,
            created_timestamp=created_ts,
        ):
            self.wfile.write(chunk)
            try:
                self.wfile.flush()
            except Exception:
                pass
        self.close_connection = True

    def _handle_ollama_chat(self, body: dict[str, Any]) -> None:
        account_id, is_teaser, is_provider_self, is_quota_exceeded = self._authenticate(allow_teaser=True)
        model_id = body.get("model", "qwen2.5:7b")
        messages = body.get("messages", [])
        stream = bool(body.get("stream", True))

        if is_quota_exceeded:
            paywall_text = get_teaser_paywall_message(self.teaser_manager.max_requests)
            if not stream:
                self._send_json(InferenceEngine.format_ollama_chat_response(
                    model_id=model_id if isinstance(model_id, str) else "computemesh",
                    completion_text=paywall_text,
                    tokens_prompt=10,
                    tokens_completion=120,
                ))
                return

            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", "application/x-ndjson")
            self.send_header("Connection", "close")
            self.end_headers()
            for chunk in InferenceEngine.stream_ollama_chat_ndjson(
                model_id=model_id if isinstance(model_id, str) else "computemesh",
                completion_text=paywall_text,
                tokens_prompt=10,
                tokens_completion=120,
            ):
                self.wfile.write(chunk)
                try:
                    self.wfile.flush()
                except Exception:
                    pass
            self.close_connection = True
            return

        if not account_id:
            return

        if not model_id or not isinstance(model_id, str):
            self._send_error_response("Missing required 'model' field", "invalid_request_error", HTTPStatus.BAD_REQUEST)
            return
        if not messages or not isinstance(messages, list):
            self._send_error_response("Missing or invalid 'messages' array", "invalid_request_error", HTTPStatus.BAD_REQUEST)
            return

        try:
            _chat_id, completion_text, _created_ts, tokens_prompt, tokens_comp = self.inference_engine.create_metered_completion(
                account_id=account_id,
                model_id=model_id,
                messages=messages,
                client_ip=self._get_client_ip(),
                is_teaser=is_teaser,
                is_provider_self_compute=is_provider_self,
            )
        except InsufficientBalanceError as e:
            self._send_error_response(str(e), "insufficient_quota", HTTPStatus.PAYMENT_REQUIRED)
            return

        if not stream:
            self._send_json(InferenceEngine.format_ollama_chat_response(
                model_id=model_id,
                completion_text=completion_text,
                tokens_prompt=tokens_prompt,
                tokens_completion=tokens_comp,
            ))
            return

        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", "application/x-ndjson")
        self.send_header("Connection", "close")
        self.end_headers()
        for chunk in InferenceEngine.stream_ollama_chat_ndjson(
            model_id=model_id,
            completion_text=completion_text,
            tokens_prompt=tokens_prompt,
            tokens_completion=tokens_comp,
        ):
            self.wfile.write(chunk)
            try:
                self.wfile.flush()
            except Exception:
                pass
        self.close_connection = True

    def _handle_ollama_generate(self, body: dict[str, Any]) -> None:
        account_id, is_teaser, is_provider_self, is_quota_exceeded = self._authenticate(allow_teaser=True)
        model_id = body.get("model", "qwen2.5:7b")
        prompt = body.get("prompt", "")
        stream = bool(body.get("stream", True))

        if is_quota_exceeded:
            paywall_text = get_teaser_paywall_message(self.teaser_manager.max_requests)
            if not stream:
                self._send_json(InferenceEngine.format_ollama_generate_response(
                    model_id=model_id if isinstance(model_id, str) else "computemesh",
                    completion_text=paywall_text,
                    tokens_prompt=10,
                    tokens_completion=120,
                ))
                return

            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", "application/x-ndjson")
            self.send_header("Connection", "close")
            self.end_headers()
            for chunk in InferenceEngine.stream_ollama_generate_ndjson(
                model_id=model_id if isinstance(model_id, str) else "computemesh",
                completion_text=paywall_text,
                tokens_prompt=10,
                tokens_completion=120,
            ):
                self.wfile.write(chunk)
                try:
                    self.wfile.flush()
                except Exception:
                    pass
            self.close_connection = True
            return

        if not account_id:
            return

        if not model_id or not isinstance(model_id, str):
            self._send_error_response("Missing required 'model' field", "invalid_request_error", HTTPStatus.BAD_REQUEST)
            return

        messages = [{"role": "user", "content": prompt}]
        try:
            _chat_id, completion_text, _created_ts, tokens_prompt, tokens_comp = self.inference_engine.create_metered_completion(
                account_id=account_id,
                model_id=model_id,
                messages=messages,
                client_ip=self._get_client_ip(),
                is_teaser=is_teaser,
                is_provider_self_compute=is_provider_self,
            )
        except InsufficientBalanceError as e:
            self._send_error_response(str(e), "insufficient_quota", HTTPStatus.PAYMENT_REQUIRED)
            return

        if not stream:
            self._send_json(InferenceEngine.format_ollama_generate_response(
                model_id=model_id,
                completion_text=completion_text,
                tokens_prompt=tokens_prompt,
                tokens_completion=tokens_comp,
            ))
            return

        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", "application/x-ndjson")
        self.send_header("Connection", "close")
        self.end_headers()
        for chunk in InferenceEngine.stream_ollama_generate_ndjson(
            model_id=model_id,
            completion_text=completion_text,
            tokens_prompt=tokens_prompt,
            tokens_completion=tokens_comp,
        ):
            self.wfile.write(chunk)
            try:
                self.wfile.flush()
            except Exception:
                pass
        self.close_connection = True


def run_gateway_server(host: str = "0.0.0.0", port: int = DEFAULT_PORT) -> None:
    server = ThreadingHTTPServer((host, port), GatewayHandler)
    print(f"ComputeMesh OpenAI-Compatible Gateway running at http://{host}:{port}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nShutting down gateway server...")
    finally:
        server.server_close()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="ComputeMesh OpenAI-Compatible Gateway Server")
    parser.add_argument("--host", default="0.0.0.0", help="Bind host (default: 0.0.0.0)")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT, help="Listen port (default: 8000)")
    args = parser.parse_args(argv)

    run_gateway_server(host=args.host, port=args.port)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
