"""ComputeMesh OpenAI & Ollama Compatible Distributed Streaming Gateway Server.

Provides OpenAI-compatible endpoints (/v1/chat/completions, /v1/models) and
Ollama-compatible endpoints (/api/chat, /api/generate, /api/tags, /api/show, /api/version),
integrated with double-entry financial metering, Stripe Connect payouts, and Free Teaser testing.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import hmac
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

from services.billing.accounting import AccountingStore
from services.billing.ledger import Ledger
from services.billing.owner_accounts import OwnerAccountStore, OwnerAccountStoreError
from services.billing.threadsafe_ledger import ThreadSafeLedger


def _resolve_owner_account_store_path() -> Path:
    env_path = os.environ.get("COMPUTEMESH_OWNER_ACCOUNTS_DB_PATH")
    if env_path:
        return Path(env_path)
    if sys.platform == "win32":
        return Path.home() / ".computemesh" / "owner_accounts.db"
    p = Path("/var/lib/computemesh/owner_accounts.db")
    try:
        p.parent.mkdir(parents=True, exist_ok=True)
        return p
    except Exception:
        return Path("/tmp/computemesh_owner_accounts.db")


OWNER_ACCOUNT_STORE = OwnerAccountStore(_resolve_owner_account_store_path())


DEFAULT_FLEET_OWNER_KEY = "inetconnector"


def owner_id_for_key(owner_key: str) -> str | None:
    """Derive a stable owner_id from a shared fleet owner key.

    The raw key is never stored; only this derived id is persisted in
    OWNER_ACCOUNT_STORE, so recovering the original key from the database is
    not possible. Nodes/queries with no owner_key fall back to the shared
    DEFAULT_FLEET_OWNER_KEY so every node belongs to a fleet by default.
    """
    cleaned = str(owner_key or "").strip() or DEFAULT_FLEET_OWNER_KEY
    return "acct_" + hashlib.sha256(cleaned.encode("utf-8")).hexdigest()[:24]


def _build_fleet_payload(owner_id: str | None, *, include_remote_urls: bool = False) -> dict[str, Any]:
    """Shared node summary for both the raw owner_key fleet API and the
    passkey-session-authenticated portal fleet view (services/portal/passkey_routes.py)."""
    from tools.appliance.hardware_detector import is_integrated_display_adapter

    bound_node_ids = set(OWNER_ACCOUNT_STORE.list_provider_nodes(owner_id)) if owner_id else set()
    live_nodes = fresh_node_telemetry_entries()
    fleet_nodes = [n for n in live_nodes if n.get("node_id") in bound_node_ids]

    nodes_out = []
    total_vram_bytes = 0
    total_tflops = 0.0
    for n in fleet_nodes:
        inv = n.get("inventory", {})
        telem = n.get("telemetry", {})
        gpus = inv.get("gpus", [])
        healthy_gpus = [
            g for g in gpus
            if not is_integrated_display_adapter(g.get("vendor", "unknown"), g.get("model_name", ""))
        ]
        node_vram = sum(g.get("vram_bytes", 0) for g in healthy_gpus)
        if not healthy_gpus and inv.get("total_vram_bytes", 0) > 0:
            node_vram = inv.get("total_vram_bytes", 0)
        node_tflops = float(telem.get("local_compute_tflops", 0.0) or 0.0)
        total_vram_bytes += node_vram
        total_tflops += node_tflops
        node_id = n.get("node_id")
        node_entry = {
            "node_id": node_id,
            "vram_gb": round(node_vram / (1024**3), 1),
            "tflops": round(node_tflops, 1),
            "gpus": [g.get("model_name") for g in gpus],
            "updated_at": n.get("updated_at"),
        }
        if include_remote_urls:
            auth_token = str(n.get("auth_token", "")).strip()
            node_entry["remote_url"] = f"/node/{node_id}?auth={auth_token}" if auth_token else None
        nodes_out.append(node_entry)

    return {
        "owner_id": owner_id,
        "total_nodes_bound": len(bound_node_ids),
        "total_nodes_online": len(fleet_nodes),
        "total_vram_gb": round(total_vram_bytes / (1024**3), 1),
        "total_tflops": round(total_tflops, 1),
        "nodes": nodes_out,
        "timestamp": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
    }


def _build_ledger_from_env() -> Ledger:
    ledger_path_env = os.environ.get("COMPUTEMESH_LEDGER_PATH")
    path = Path(ledger_path_env) if ledger_path_env else None
    if os.environ.get("COMPUTEMESH_UNIFIED_OWNER_CREDITS", "").strip().lower() in ("1", "true", "yes", "on"):
        from services.billing.owner_gateway_ledger import GatewayOwnerCreditLedger
        return GatewayOwnerCreditLedger(storage_path=path)
    return ThreadSafeLedger(storage_path=path)
from services.billing.stripe_connect import SettlementExecutor, StripeConnectService
from services.billing.stripe_integration import StripePaymentService, StripeSessionStore
from services.common.config import CONFIG
from services.gateway.auth import GatewayAuthManager, extract_bearer_token, resolve_client_ip
from services.gateway.catalog import AVAILABLE_MODELS, resolve_model_id
from services.gateway.dashboard import (
    NODE_TELEMETRY_REGISTRY,
    fresh_node_telemetry_entries,
    render_node_remote_dashboard_html,
    save_node_telemetry_registry,
)
from services.gateway.inference import InferenceEngine
from services.gateway.metrics_exporter import MetricsRegistry
from services.gateway.routes_billing import BillingRoutesHandler
from services.gateway.routes_provider import ProviderRoutesHandler
from services.gateway.security import (
    GLOBAL_RATE_LIMITER,
    MAX_REQUEST_PAYLOAD_BYTES,
    SECURITY_HEADERS,
    sanitize_error_message,
)
from services.gateway.teaser import TeaserQuotaManager, get_teaser_paywall_message
from services.portal.passkey_routes import PasskeyAuthHandler, session_account_from_headers

DEFAULT_PORT = CONFIG.default_gateway_port





def _build_account_store_from_env() -> AccountingStore | None:
    store_path_env = os.environ.get("COMPUTEMESH_ACCOUNTING_DB_PATH")
    if not store_path_env:
        return None
    return AccountingStore(storage_path=Path(store_path_env))


def _build_stripe_service(ledger: Ledger, account_store: AccountingStore | None = None) -> StripePaymentService:
    webhook_secret = os.environ.get("STRIPE_WEBHOOK_SECRET", "").strip()
    stripe_api_key = os.environ.get("STRIPE_API_KEY", "").strip()
    session_store_path_env = os.environ.get("COMPUTEMESH_STRIPE_SESSION_STORE_PATH")
    session_store = StripeSessionStore(Path(session_store_path_env)) if session_store_path_env else None
    return StripePaymentService(
        ledger=ledger,
        webhook_secret=webhook_secret,
        stripe_api_key=stripe_api_key,
        session_store=session_store,
        webhook_event_store=account_store,
    )


def _build_settlement_executor(ledger: Ledger, account_store: AccountingStore | None = None) -> SettlementExecutor | None:
    if not account_store:
        return None
    stripe_api_key = os.environ.get("STRIPE_API_KEY", "").strip()
    return SettlementExecutor(
        ledger=ledger,
        account_store=account_store,
        stripe_connect=StripeConnectService(stripe_api_key=stripe_api_key),
    )


class GatewayHandler(BaseHTTPRequestHandler):
    """High-performance Hardened HTTP Request Handler for OpenAI and Ollama APIs."""

    server_version = "ComputeMesh-Gateway/1.2"
    sys_version = ""

    ledger: Ledger = _build_ledger_from_env()
    account_store: AccountingStore | None = _build_account_store_from_env()
    stripe_svc: StripePaymentService = _build_stripe_service(ledger, account_store)
    settlement_executor: SettlementExecutor | None = _build_settlement_executor(ledger, account_store)
    metrics: MetricsRegistry = MetricsRegistry()
    teaser_manager: TeaserQuotaManager = TeaserQuotaManager(
        max_requests=CONFIG.teaser.max_free_requests,
        max_tokens=CONFIG.teaser.max_free_tokens,
        window_seconds=CONFIG.teaser.window_seconds,
    )
    auth_manager: GatewayAuthManager = GatewayAuthManager(ledger=ledger, teaser_manager=teaser_manager, owner_account_store=OWNER_ACCOUNT_STORE)
    billing_routes: BillingRoutesHandler = BillingRoutesHandler(ledger=ledger, stripe_svc=stripe_svc, auth_manager=auth_manager)
    provider_routes: ProviderRoutesHandler = ProviderRoutesHandler(account_store=account_store, settlement_executor=settlement_executor, auth_manager=auth_manager, ledger=ledger)
    inference_engine: InferenceEngine = InferenceEngine(ledger=ledger, metrics=metrics, teaser_manager=teaser_manager)
    passkey_handler: PasskeyAuthHandler = PasskeyAuthHandler()

    @classmethod
    def sync_subsystems(cls) -> None:
        """Synchronizes sub-handlers when class-level dependencies are modified."""
        cls.auth_manager = GatewayAuthManager(ledger=cls.ledger, teaser_manager=cls.teaser_manager, api_keys=getattr(cls, "api_keys", {}), owner_account_store=OWNER_ACCOUNT_STORE)
        cls.billing_routes = BillingRoutesHandler(ledger=cls.ledger, stripe_svc=cls.stripe_svc, auth_manager=cls.auth_manager)
        cls.provider_routes = ProviderRoutesHandler(account_store=cls.account_store, settlement_executor=cls.settlement_executor, auth_manager=cls.auth_manager, ledger=cls.ledger)
        backend = getattr(getattr(cls, "inference_engine", None), "backend", None)
        cls.inference_engine = InferenceEngine(ledger=cls.ledger, metrics=cls.metrics, teaser_manager=cls.teaser_manager, backend=backend)

    def log_message(self, format: str, *args: Any) -> None:
        pass

    def _check_rate_limit(self) -> bool:
        client_ip = resolve_client_ip(self.headers, getattr(self, "client_address", None))
        auth_token = extract_bearer_token(self.headers)
        is_authenticated = bool(auth_token) and self.auth_manager.is_valid_key(auth_token)
        rate_id = f"token_{auth_token}" if is_authenticated else f"ip_{client_ip}"
        allowed, retry_after = GLOBAL_RATE_LIMITER.is_allowed(rate_id, is_authenticated=is_authenticated)
        if not allowed:
            self._send_rate_limit_response(retry_after)
            return False
        return True

    def _send_rate_limit_response(self, retry_after: float) -> None:
        payload = {
            "error": {
                "message": f"Too many requests. Rate limit exceeded. Retry in {retry_after}s.",
                "type": "rate_limit_error",
                "code": 429,
            }
        }
        body = json.dumps(payload, indent=2).encode("utf-8")
        self.send_response(HTTPStatus.TOO_MANY_REQUESTS)
        self.send_header("Content-Type", "application/json")
        for h_name, h_val in SECURITY_HEADERS.items():
            self.send_header(h_name, h_val)
        self.send_header("Retry-After", str(int(retry_after) + 1))
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Connection", "close")
        self.end_headers()
        self.wfile.write(body)
        self.close_connection = True

    def _send_json(
        self,
        data: dict[str, Any],
        status: HTTPStatus = HTTPStatus.OK,
        extra_headers: dict[str, str] | None = None,
    ) -> None:
        body = json.dumps(data, indent=2).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        for h_name, h_val in SECURITY_HEADERS.items():
            self.send_header(h_name, h_val)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, Authorization, X-Forwarded-For, Stripe-Signature")
        self.send_header(
            "Access-Control-Expose-Headers",
            "X-ComputeMesh-Teaser-Remaining, X-ComputeMesh-Teaser-Limit, "
            "X-ComputeMesh-Teaser-Reset-Seconds, X-ComputeMesh-Teaser-Reset-At, Retry-After",
        )
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        for h_name, h_val in (extra_headers or {}).items():
            self.send_header(h_name, h_val)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Connection", "close")
        self.end_headers()
        self.wfile.write(body)
        try:
            self.wfile.flush()
        except Exception:
            pass
        self.close_connection = True

    def _send_teaser_quota_response(self, client_ip: str) -> None:
        headers = self.teaser_manager.response_headers(client_ip)
        retry_after = headers.get("X-ComputeMesh-Teaser-Reset-Seconds", "3600")
        headers["Retry-After"] = retry_after
        limit = self.teaser_manager.max_requests
        reset_minutes = max(1, (int(retry_after) + 59) // 60)
        paywall = get_teaser_paywall_message(limit)
        message = (
            f"Free teaser limit reached ({limit}/{limit}). "
            f"Your demo quota refreshes automatically in about {reset_minutes} minutes."
        )
        payload = {
            "message": message,
            "error": {
                "message": message,
                "type": "teaser_quota_exceeded",
                "code": 429,
            },
            "teaser": {
                "remaining_requests": 0,
                "limit": limit,
                "retry_after_seconds": int(retry_after),
                "reset_at": headers.get("X-ComputeMesh-Teaser-Reset-At", ""),
                "upgrade_message": paywall,
            },
        }
        self._send_json(payload, HTTPStatus.TOO_MANY_REQUESTS, headers)

    def _send_error_response(self, message: str, error_type: str, status: HTTPStatus | int) -> None:
        status_val = status.value if isinstance(status, HTTPStatus) else int(status)
        try:
            http_status = HTTPStatus(status_val)
        except ValueError:
            http_status = HTTPStatus.BAD_REQUEST
        clean_msg = sanitize_error_message(message)
        payload = {
            "error": {
                "message": clean_msg,
                "type": error_type,
                "code": status_val,
            }
        }
        self._send_json(payload, http_status)

    def do_OPTIONS(self) -> None:
        self.send_response(HTTPStatus.OK)
        for h_name, h_val in SECURITY_HEADERS.items():
            self.send_header(h_name, h_val)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, Authorization, X-Forwarded-For, Stripe-Signature")
        self.send_header("Connection", "close")
        self.end_headers()
        self.close_connection = True

    def do_GET(self) -> None:
        if not self._check_rate_limit():
            return

        parsed_path = urlparse(self.path)
        clean_path = parsed_path.path.rstrip("/")
        query = parse_qs(parsed_path.query)

        if clean_path in ("/metrics", "/v1/metrics"):
            text = self.metrics.render_prometheus_text()
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", "text/plain; version=0.0.4; charset=utf-8")
            for h_name, h_val in SECURITY_HEADERS.items():
                self.send_header(h_name, h_val)
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

            if not node_id or node_id not in NODE_TELEMETRY_REGISTRY:
                self._send_error_response(f"Node '{node_id}' not found in cluster telemetry registry.", "not_found", HTTPStatus.NOT_FOUND)
                return

            node_data = NODE_TELEMETRY_REGISTRY[node_id]
            expected_auth_token = str(node_data.get("auth_token", "")).strip()

            # Enforce authentication if node telemetry is protected with an auth token
            if expected_auth_token:
                if not auth_token or not hmac.compare_digest(auth_token, expected_auth_token):
                    self._send_error_response("Unauthorized: Valid auth token required to view this node's telemetry.", "unauthorized", HTTPStatus.UNAUTHORIZED)
                    return

            html = render_node_remote_dashboard_html(node_id, auth_token, node_data)
            body = html.encode("utf-8")
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            for h_name, h_val in SECURITY_HEADERS.items():
                self.send_header(h_name, h_val)
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
            self._send_json({"version": f"0.5.7-computemesh-{CONFIG.appliance_version}"})
            return

        if clean_path in ("/mesh/stats", "/api/v1/mesh/stats"):
            live_nodes = fresh_node_telemetry_entries()
            if not live_nodes:
                payload = {
                    "source": "not_configured",
                    "active_gpus": 0,
                    "total_vram_gb": 0,
                    "total_nodes": 0,
                    "total_tflops": 0.0,
                    "tokens_served_today": 0,
                    "average_latency_ms": None,
                    "network_uptime_percent": None,
                    "measurement_status": "not_measured",
                    "timestamp": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
                }
            else:
                from tools.appliance.hardware_detector import is_integrated_display_adapter
                total_vram_bytes = 0
                total_gpus = 0
                for n in live_nodes:
                    inv = n.get("inventory", {})
                    gpus = inv.get("gpus", [])
                    healthy_gpus = [
                        g for g in gpus
                        if not is_integrated_display_adapter(g.get("vendor", "unknown"), g.get("model_name", ""))
                    ]
                    node_vram = sum(g.get("vram_bytes", 0) for g in healthy_gpus)
                    if not healthy_gpus and inv.get("total_vram_bytes", 0) > 0 and not is_integrated_display_adapter("unknown", inv.get("host_architecture", "")):
                        node_vram = inv.get("total_vram_bytes", 0)
                        healthy_gpus = [1]
                    total_vram_bytes += node_vram
                    total_gpus += len(healthy_gpus)

                total_vram = total_vram_bytes / (1024**3)
                total_tflops = sum(float(n.get("telemetry", {}).get("local_compute_tflops", 0.0) or 0.0) for n in live_nodes)
                total_nodes = len(live_nodes)
                tokens = sum(int(n.get("telemetry", {}).get("tokens_processed", 0) or 0) for n in live_nodes)

                payload = {
                    "source": "authenticated_cluster",
                    "active_gpus": total_gpus,
                    "total_vram_gb": round(total_vram, 1),
                    "total_nodes": total_nodes,
                    "total_tflops": round(total_tflops, 1),
                    "tokens_served_today": tokens,
                    "average_latency_ms": None,
                    "network_uptime_percent": None,
                    "measurement_status": "live",
                    "timestamp": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
                }
            self._send_json(payload)
            return

        if clean_path in ("/api/v1/mesh/fleet", "/mesh/fleet"):
            owner_key = query.get("owner_key", [""])[0].strip() or self.headers.get("X-Owner-Key", "").strip()
            if not owner_key:
                auth_hdr = self.headers.get("Authorization", "").strip()
                if auth_hdr.startswith("Bearer "):
                    candidate = auth_hdr[7:].strip()
                    if candidate.startswith("owner_") or candidate.startswith("cm_owner_"):
                        owner_key = candidate
            owner_id = owner_id_for_key(owner_key) if owner_key else None
            self._send_json(_build_fleet_payload(owner_id, include_remote_urls=True))
            return

        if clean_path == "/api/auth/me":
            account = session_account_from_headers(self.headers)
            if account is None:
                self._send_json({"error": "not signed in"}, HTTPStatus.UNAUTHORIZED)
                return
            self._send_json({"account_id": account.account_id, "email": account.email, "owner_key": account.owner_key})
            return

        if clean_path == "/api/portal/fleet":
            account = session_account_from_headers(self.headers)
            owner_key = ""
            if account is not None:
                owner_key = account.owner_key
            else:
                owner_key = query.get("owner_key", [""])[0].strip() or self.headers.get("X-Owner-Key", "").strip()
                if not owner_key:
                    auth_hdr = self.headers.get("Authorization", "").strip()
                    if auth_hdr.startswith("Bearer "):
                        candidate = auth_hdr[7:].strip()
                        if candidate.startswith("owner_") or candidate.startswith("cm_owner_"):
                            owner_key = candidate
            if not owner_key and account is None:
                self._send_json({"error": "not signed in"}, HTTPStatus.UNAUTHORIZED)
                return
            owner_id = owner_id_for_key(owner_key)
            payload = _build_fleet_payload(owner_id, include_remote_urls=True)
            self._send_json(payload)
            return

        if clean_path in ("/api/v1/pricing", "/v1/pricing", "/pricing"):
            from services.common.pricing import DEFAULT_PRICE_TIERS, MICRO_UNITS_PER_USD
            tiers_data = {
                m_id: {
                    "model_id": tier.model_id,
                    "prompt_usd_per_million": tier.prompt_usd_per_million,
                    "completion_usd_per_million": tier.completion_usd_per_million,
                    "blended_usd_per_million": round(tier.blended_usd_per_million, 4),
                    "cloud_reference_usd_per_million": tier.cloud_reference_usd_per_million,
                    "provider_share_ratio": 0.75,
                }
                for m_id, tier in DEFAULT_PRICE_TIERS.items()
            }
            self._send_json({
                "currency": "USD",
                "micro_units_per_usd": MICRO_UNITS_PER_USD,
                "credits_per_usd": MICRO_UNITS_PER_USD,
                "tiers": tiers_data,
            })
            return

        if clean_path == "/v1/billing/balance":
            res, err, status = self.billing_routes.handle_get_balance(self.headers)
            if err:
                self._send_error_response(err, "billing_error", status)
            else:
                self._send_json(res or {}, status)
            return

        if clean_path == "/v1/providers/status":
            res, err, status = self.provider_routes.handle_status(self.headers)
            if err:
                self._send_error_response(err, "provider_error", status)
            else:
                self._send_json(res or {}, status)
            return

        if clean_path == "/v1/admin/providers":
            res, err, status = self.provider_routes.handle_admin_list_providers(self.headers)
            if err:
                self._send_error_response(err, "admin_error", status)
            else:
                self._send_json(res or {}, status)
            return

        if clean_path == "/v1/admin/settlements":
            res, err, status = self.provider_routes.handle_admin_list_settlements(self.headers, query)
            if err:
                self._send_error_response(err, "admin_error", status)
            else:
                self._send_json(res or {}, status)
            return

        self._send_error_response("Not Found", "invalid_request_error", HTTPStatus.NOT_FOUND)

    def do_POST(self) -> None:
        if not self._check_rate_limit():
            return

        parsed_path = urlparse(self.path)
        clean_path = parsed_path.path.rstrip("/")

        content_length_hdr = self.headers.get("Content-Length")
        if not content_length_hdr:
            self._send_error_response("Content-Length header required", "invalid_request_error", HTTPStatus.BAD_REQUEST)
            return

        try:
            content_length = int(content_length_hdr)
        except ValueError:
            self._send_error_response("Invalid Content-Length header", "invalid_request_error", HTTPStatus.BAD_REQUEST)
            return

        if content_length > MAX_REQUEST_PAYLOAD_BYTES:
            self._send_error_response(
                f"Payload exceeds maximum allowed size ({MAX_REQUEST_PAYLOAD_BYTES} bytes)",
                "payload_too_large",
                HTTPStatus.REQUEST_ENTITY_TOO_LARGE,
            )
            return

        raw_body = self.rfile.read(content_length)

        if clean_path == "/v1/billing/webhook":
            res, err, status = self.billing_routes.handle_post_webhook(self.headers, raw_body)
            if err:
                self._send_error_response(err, "webhook_error", status)
            else:
                self._send_json(res or {}, status)
            return

        try:
            body = json.loads(raw_body.decode("utf-8")) if raw_body else {}
        except Exception:
            self._send_error_response("Malformed JSON request body", "invalid_request_error", HTTPStatus.BAD_REQUEST)
            return

        if clean_path == "/api/auth/register/begin":
            data, status, cookie = self.passkey_handler.register_begin(body)
            self._send_json(data, status, extra_headers={"Set-Cookie": cookie} if cookie else None)
            return

        if clean_path == "/api/auth/register/complete":
            data, status, cookie = self.passkey_handler.register_complete(body)
            self._send_json(data, status, extra_headers={"Set-Cookie": cookie} if cookie else None)
            return

        if clean_path == "/api/auth/login/begin":
            data, status, cookie = self.passkey_handler.login_begin(body)
            self._send_json(data, status, extra_headers={"Set-Cookie": cookie} if cookie else None)
            return

        if clean_path == "/api/auth/login/complete":
            data, status, cookie = self.passkey_handler.login_complete(body)
            self._send_json(data, status, extra_headers={"Set-Cookie": cookie} if cookie else None)
            return

        if clean_path == "/api/auth/logout":
            data, status, cookie = self.passkey_handler.logout(self.headers)
            self._send_json(data, status, extra_headers={"Set-Cookie": cookie} if cookie else None)
            return

        if clean_path in ("/api/v1/node/heartbeat", "/api/node/heartbeat", "/v1/node/heartbeat"):
            node_id = str(body.get("node_id", "")).strip()
            auth_token = str(body.get("auth_token", "")).strip()
            if not node_id:
                self._send_error_response("Valid node_id is required", "invalid_request_error", HTTPStatus.BAD_REQUEST)
                return

            if not auth_token:
                self._send_error_response("Non-empty auth_token is required for node authentication", "unauthorized", HTTPStatus.UNAUTHORIZED)
                return

            existing_node = NODE_TELEMETRY_REGISTRY.get(node_id)
            if existing_node:
                expected_token = str(existing_node.get("auth_token", "")).strip()
                updated_at_str = str(existing_node.get("updated_at", "")).strip()
                is_stale = False
                if updated_at_str:
                    try:
                        ts = datetime.fromisoformat(updated_at_str.replace("Z", "+00:00"))
                        if (datetime.now(timezone.utc) - ts).total_seconds() > 300:
                            is_stale = True
                    except Exception:
                        is_stale = True
                if expected_token and not is_stale and not hmac.compare_digest(auth_token, expected_token):
                    self._send_error_response("Unauthorized: auth_token mismatch for active node", "unauthorized", HTTPStatus.UNAUTHORIZED)
                    return

            owner_key = str(body.get("owner_key", "")).strip()
            owner_binding_error: str | None = None
            owner_id = owner_id_for_key(owner_key)
            if owner_id:
                try:
                    OWNER_ACCOUNT_STORE.ensure_owner(owner_id)
                    OWNER_ACCOUNT_STORE.bind_provider_node(owner_id, node_id)
                except OwnerAccountStoreError as exc:
                    # Do not fail the heartbeat over a fleet-binding conflict
                    # (e.g. this node_id already belongs to a different
                    # owner_key) -- telemetry/pricing must keep working.
                    owner_binding_error = str(exc)
                    owner_id = OWNER_ACCOUNT_STORE.owner_for_provider_node(node_id)

            now_iso = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
            NODE_TELEMETRY_REGISTRY[node_id] = {
                "node_id": node_id,
                "auth_token": auth_token,
                "owner_id": owner_id,
                "inventory": body.get("inventory", {}),
                "telemetry": body.get("telemetry", {}),
                "global_mesh": body.get("global_mesh", {}),
                "software": body.get("software", {}),
                "updated_at": now_iso,
            }

            # Register discovered cluster peers (e.g. LAN miners or secondary appliances)
            gm = body.get("global_mesh", {})
            for peer in gm.get("nodes", []):
                p_id = str(peer.get("node_id", "")).strip()
                if p_id and p_id != node_id and p_id not in ("windows-laptop", "unnamed-node"):
                    p_vram_gb = float(peer.get("vram_gb", 0.0))
                    p_vram_bytes = int(p_vram_gb * 1024 * 1024 * 1024)
                    p_tflops = float(peer.get("tflops", 0.0))
                    p_gpus_cnt = int(peer.get("gpus_count", 1))

                    if p_id not in NODE_TELEMETRY_REGISTRY or NODE_TELEMETRY_REGISTRY[p_id].get("is_peer_relay", False):
                        NODE_TELEMETRY_REGISTRY[p_id] = {
                            "node_id": p_id,
                            # Deliberately no auth_token: a synthetic token here
                            # would permanently lock the real node p_id out of
                            # its own registry slot, since its real auth_token
                            # would then never match this placeholder and every
                            # subsequent direct heartbeat from p_id would be
                            # rejected as a mismatch until 5-minute staleness.
                            "auth_token": "",
                            "is_peer_relay": True,
                            "inventory": {
                                "total_vram_bytes": p_vram_bytes,
                                "total_gpus": p_gpus_cnt,
                                "gpus": [
                                    {
                                        "vendor": "amd" if "amd" in str(peer.get("gpu_summary", "")).lower() else "nvidia",
                                        "model_name": str(peer.get("gpu_summary", "Cluster GPU Node")),
                                        "vram_bytes": p_vram_bytes // max(1, p_gpus_cnt),
                                        "healthy": True,
                                    }
                                ],
                            },
                            "telemetry": {
                                "tokens_processed": peer.get("tokens", 0),
                                "local_compute_tflops": p_tflops,
                                "is_simulated": False,
                            },
                            "updated_at": now_iso,
                        }

            save_node_telemetry_registry(NODE_TELEMETRY_REGISTRY)
            resp = {"status": "ok", "message": "heartbeat registered", "node_id": node_id}
            if owner_binding_error:
                resp["owner_binding_error"] = owner_binding_error
            self._send_json(resp)
            return

        if clean_path in ("/api/v1/billing/quote", "/v1/billing/quote"):
            from services.portal.routes_quotes import PortalQuotesHandler
            quotes_handler = PortalQuotesHandler()
            res, err, status = quotes_handler.handle_quote(body)
            if err:
                self._send_error_response(err, "quote_error", status)
            else:
                self._send_json(res or {}, status)
            return

        if clean_path in ("/api/v1/register", "/v1/register"):
            from services.portal.routes_registration import PortalRegistrationHandler
            reg_handler = PortalRegistrationHandler()
            res, err, status = reg_handler.handle_register(body)
            if err:
                self._send_error_response(err, "registration_error", status)
            else:
                self._send_json(res or {}, status)
            return

        if clean_path in ("/v1/billing/topup", "/api/v1/billing/topup"):
            res, err, status = self.billing_routes.handle_post_topup(self.headers, body)
            if err:
                self._send_error_response(err, "billing_error", status)
            else:
                self._send_json(res or {}, status)
            return

        if clean_path in ("/v1/billing/checkout", "/api/v1/billing/checkout"):
            res, err, status = self.billing_routes.handle_post_checkout(self.headers, body)
            if err:
                self._send_error_response(err, "stripe_error", status)
            else:
                self._send_json(res or {}, status)
            return

        if clean_path == "/v1/providers/register":
            res, err, status = self.provider_routes.handle_register(self.headers, body)
            if err:
                self._send_error_response(err, "provider_error", status)
            else:
                self._send_json(res or {}, status)
            return

        if clean_path in ("/v1/providers/stripe/onboard", "/v1/providers/stripe/onboarding"):
            res, err, status = self.provider_routes.handle_stripe_onboard(self.headers, body)
            if err:
                self._send_error_response(err, "stripe_error", status)
            else:
                self._send_json(res or {}, status)
            return

        if clean_path == "/v1/providers/stripe/refresh":
            res, err, status = self.provider_routes.handle_stripe_refresh(self.headers)
            if err:
                self._send_error_response(err, "stripe_error", status)
            else:
                self._send_json(res or {}, status)
            return

        if clean_path == "/v1/admin/settlements/provider":
            res, err, status = self.provider_routes.handle_admin_settlement(self.headers, body)
            if err:
                self._send_error_response(err, "settlement_error", status)
            else:
                self._send_json(res or {}, status)
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

    def _handle_ollama_show(self, body: dict[str, Any]) -> None:
        requested = str(body.get("name", "") or body.get("model", "")).strip()
        model_id = resolve_model_id(requested)
        self._send_json({
            "modelfile": f"# ComputeMesh Dynamic Modelfile\nFROM {model_id}\nTEMPLATE \"\"\"{{{{ .Prompt }}}}\"\"\"",
            "parameters": f"stop                           \"<|im_end|>\"\ncontext_length                 32768",
            "template": "{{ .Prompt }}",
            "details": {
                "parent_model": "",
                "format": "gguf",
                "family": "qwen2" if "qwen" in model_id else "llama",
                "families": ["qwen2" if "qwen" in model_id else "llama"],
                "parameter_size": "7.6B" if "7b" in model_id else "70.6B",
                "quantization_level": "Q4_K_M",
            },
            "model_info": {
                "general.architecture": "qwen2" if "qwen" in model_id else "llama",
                "general.file_type": 15,
                "general.parameter_count": 7615616512,
            },
        })

    def _handle_chat_completions(self, body: dict[str, Any]) -> None:
        auth = self.auth_manager.authenticate_request(self.headers, getattr(self, "client_address", None), allow_teaser=True)
        if not auth.is_authenticated:
            self._send_error_response(auth.error_message or "Unauthorized", "authentication_error", auth.status_code)
            return

        model_req = str(body.get("model", "qwen/qwen2.5-7b-instruct"))
        model_id = resolve_model_id(model_req)
        messages = body.get("messages", [])
        stream = bool(body.get("stream", False))
        max_tokens_val = body.get("max_tokens") or body.get("max_completion_tokens")
        max_tokens = int(max_tokens_val) if max_tokens_val is not None and str(max_tokens_val).isdigit() else None
        client_ip = resolve_client_ip(self.headers, getattr(self, "client_address", None))

        if auth.is_quota_exceeded:
            self._send_teaser_quota_response(client_ip)
            return

        if not stream:
            res, err, status = self.inference_engine.execute_chat_completion(
                account_id=auth.account_id or "cust_default",
                model_id=model_id,
                messages=messages,
                is_teaser=auth.is_teaser,
                is_provider_self_compute=auth.is_provider_self_compute,
                client_ip=client_ip,
                max_tokens=max_tokens,
            )
            if err:
                self._send_error_response(err, "inference_error", status)
            else:
                headers = self.teaser_manager.response_headers(client_ip) if auth.is_teaser else None
                self._send_json(res or {}, HTTPStatus(status), headers)
            return

        # SSE Streaming response
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", "text/event-stream; charset=utf-8")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Connection", "close")
        self.end_headers()
        for chunk in self.inference_engine.stream_chat_completions(
            account_id=auth.account_id or "cust_default",
            model_id=model_id,
            messages=messages,
            is_teaser=auth.is_teaser,
            is_provider_self_compute=auth.is_provider_self_compute,
            client_ip=client_ip,
            max_tokens=max_tokens,
        ):
            self.wfile.write(chunk)
            self.wfile.flush()
        self.close_connection = True

    def _handle_ollama_chat(self, body: dict[str, Any]) -> None:
        auth = self.auth_manager.authenticate_request(self.headers, getattr(self, "client_address", None), allow_teaser=True)
        if not auth.is_authenticated:
            self._send_error_response(auth.error_message or "Unauthorized", "authentication_error", auth.status_code)
            return

        model_req = str(body.get("model", "qwen/qwen2.5-7b-instruct"))
        model_id = resolve_model_id(model_req)
        messages = body.get("messages", [])
        stream = bool(body.get("stream", True))
        opt_predict = body.get("options", {}).get("num_predict") if isinstance(body.get("options"), dict) else None
        max_tokens = int(opt_predict) if opt_predict is not None and str(opt_predict).isdigit() else None
        client_ip = resolve_client_ip(self.headers, getattr(self, "client_address", None))

        if auth.is_quota_exceeded:
            self._send_teaser_quota_response(client_ip)
            return

        if not stream:
            res, err, status = self.inference_engine.execute_ollama_chat(
                account_id=auth.account_id or "cust_default",
                model_id=model_id,
                messages=messages,
                is_teaser=auth.is_teaser,
                is_provider_self_compute=auth.is_provider_self_compute,
                client_ip=client_ip,
                max_tokens=max_tokens,
            )
            if err:
                self._send_error_response(err, "inference_error", status)
            else:
                headers = self.teaser_manager.response_headers(client_ip) if auth.is_teaser else None
                self._send_json(res or {}, HTTPStatus(status), headers)
            return

        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", "application/x-ndjson; charset=utf-8")
        self.send_header("Connection", "close")
        self.end_headers()
        for chunk in self.inference_engine.stream_ollama_chat(
            account_id=auth.account_id or "cust_default",
            model_id=model_id,
            messages=messages,
            is_teaser=auth.is_teaser,
            is_provider_self_compute=auth.is_provider_self_compute,
            client_ip=client_ip,
            max_tokens=max_tokens,
        ):
            self.wfile.write(chunk)
            self.wfile.flush()
        self.close_connection = True

    def _handle_ollama_generate(self, body: dict[str, Any]) -> None:
        auth = self.auth_manager.authenticate_request(self.headers, getattr(self, "client_address", None), allow_teaser=True)
        if not auth.is_authenticated:
            self._send_error_response(auth.error_message or "Unauthorized", "authentication_error", auth.status_code)
            return

        model_req = str(body.get("model", "qwen/qwen2.5-7b-instruct"))
        model_id = resolve_model_id(model_req)
        prompt = body.get("prompt", "")
        stream = bool(body.get("stream", True))
        opt_predict = body.get("options", {}).get("num_predict") if isinstance(body.get("options"), dict) else None
        max_tokens = int(opt_predict) if opt_predict is not None and str(opt_predict).isdigit() else None
        client_ip = resolve_client_ip(self.headers, getattr(self, "client_address", None))

        if auth.is_quota_exceeded:
            self._send_teaser_quota_response(client_ip)
            return

        if not stream:
            res, err, status = self.inference_engine.execute_ollama_generate(
                account_id=auth.account_id or "cust_default",
                model_id=model_id,
                prompt=prompt,
                is_teaser=auth.is_teaser,
                is_provider_self_compute=auth.is_provider_self_compute,
                client_ip=client_ip,
                max_tokens=max_tokens,
            )
            if err:
                self._send_error_response(err, "inference_error", status)
            else:
                headers = self.teaser_manager.response_headers(client_ip) if auth.is_teaser else None
                self._send_json(res or {}, HTTPStatus(status), headers)
            return

        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", "application/x-ndjson; charset=utf-8")
        self.send_header("Connection", "close")
        self.end_headers()
        for chunk in self.inference_engine.stream_ollama_generate(
            account_id=auth.account_id or "cust_default",
            model_id=model_id,
            prompt=prompt,
            is_teaser=auth.is_teaser,
            is_provider_self_compute=auth.is_provider_self_compute,
            client_ip=client_ip,
            max_tokens=max_tokens,
        ):
            self.wfile.write(chunk)
            self.wfile.flush()
        self.close_connection = True


def create_gateway_server(host: str = "127.0.0.1", port: int = 0) -> tuple[ThreadingHTTPServer, int]:
    """Creates a ThreadingHTTPServer instance bound to host and port."""
    server = ThreadingHTTPServer((host, port), GatewayHandler)
    bound_port = server.server_address[1]
    return server, bound_port


def run_gateway_server(host: str = "0.0.0.0", port: int = DEFAULT_PORT) -> None:
    server, bound_port = create_gateway_server(host, port)
    print(f"ComputeMesh Gateway Server listening on http://{host}:{bound_port}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nShutting down Gateway server...")
    finally:
        server.server_close()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="ComputeMesh OpenAI/Ollama Compatible Gateway Server")
    parser.add_argument("--host", default="0.0.0.0", help="Host address to bind (default: 0.0.0.0)")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT, help=f"Port to listen on (default: {DEFAULT_PORT})")
    args = parser.parse_args(argv)

    run_gateway_server(host=args.host, port=args.port)
    return 0


if __name__ == "__main__":
    sys.exit(main())
