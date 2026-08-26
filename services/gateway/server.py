"""ComputeMesh OpenAI & Ollama Compatible Distributed Streaming Gateway Server.

Provides OpenAI-compatible endpoints (/v1/chat/completions, /v1/models) and
Ollama-compatible endpoints (/api/chat, /api/generate, /api/tags, /api/show, /api/version),
integrated with double-entry financial metering, Stripe Connect payouts, and Free Teaser testing.
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

from services.billing.accounting import AccountingStore
from services.billing.ledger import Ledger
from services.billing.stripe_connect import SettlementExecutor, StripeConnectService
from services.billing.stripe_integration import StripePaymentService, StripeSessionStore
from services.common.config import CONFIG
from services.gateway.auth import GatewayAuthManager, extract_bearer_token, resolve_client_ip
from services.gateway.catalog import AVAILABLE_MODELS, resolve_model_id
from services.gateway.dashboard import (
    NODE_TELEMETRY_REGISTRY,
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

DEFAULT_PORT = CONFIG.default_gateway_port


def _build_ledger_from_env() -> Ledger:
    ledger_path_env = os.environ.get("COMPUTEMESH_LEDGER_PATH")
    path = Path(ledger_path_env) if ledger_path_env else None
    return Ledger(storage_path=path)


def _build_account_store_from_env() -> AccountingStore | None:
    store_path_env = os.environ.get("COMPUTEMESH_ACCOUNTING_DB_PATH")
    if not store_path_env:
        return None
    return AccountingStore(sqlite_path=Path(store_path_env))


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
    """High-performance Military-Grade HTTP Request Handler for OpenAI and Ollama APIs."""

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
    auth_manager: GatewayAuthManager = GatewayAuthManager(ledger=ledger, teaser_manager=teaser_manager)
    billing_routes: BillingRoutesHandler = BillingRoutesHandler(ledger=ledger, stripe_svc=stripe_svc, auth_manager=auth_manager)
    provider_routes: ProviderRoutesHandler = ProviderRoutesHandler(account_store=account_store, settlement_executor=settlement_executor, auth_manager=auth_manager, ledger=ledger)
    inference_engine: InferenceEngine = InferenceEngine(ledger=ledger, metrics=metrics, teaser_manager=teaser_manager)

    @classmethod
    def sync_subsystems(cls) -> None:
        """Synchronizes sub-handlers when class-level dependencies are modified."""
        cls.auth_manager = GatewayAuthManager(ledger=cls.ledger, teaser_manager=cls.teaser_manager, api_keys=getattr(cls, "api_keys", {}))
        cls.billing_routes = BillingRoutesHandler(ledger=cls.ledger, stripe_svc=cls.stripe_svc, auth_manager=cls.auth_manager)
        cls.provider_routes = ProviderRoutesHandler(account_store=cls.account_store, settlement_executor=cls.settlement_executor, auth_manager=cls.auth_manager, ledger=cls.ledger)
        cls.inference_engine = InferenceEngine(ledger=cls.ledger, metrics=cls.metrics, teaser_manager=cls.teaser_manager)

    def log_message(self, format: str, *args: Any) -> None:
        pass

    def _check_rate_limit(self) -> bool:
        client_ip = resolve_client_ip(self.headers, getattr(self, "client_address", None))
        auth_token = extract_bearer_token(self.headers)
        rate_id = f"token_{auth_token}" if auth_token else f"ip_{client_ip}"
        allowed, retry_after = GLOBAL_RATE_LIMITER.is_allowed(rate_id, is_authenticated=bool(auth_token))
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
            node_data = NODE_TELEMETRY_REGISTRY.get(node_id, {})
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

        if clean_path in ("/api/v1/node/heartbeat", "/api/node/heartbeat", "/v1/node/heartbeat"):
            node_id = str(body.get("node_id", "")).strip()
            auth_token = str(body.get("auth_token", "")).strip()
            if not node_id:
                self._send_error_response("Valid node_id is required", "invalid_request_error", HTTPStatus.BAD_REQUEST)
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
            save_node_telemetry_registry(NODE_TELEMETRY_REGISTRY)
            self._send_json({"status": "ok", "message": "heartbeat registered", "node_id": node_id})
            return

        if clean_path == "/v1/billing/topup":
            res, err, status = self.billing_routes.handle_post_topup(self.headers, body)
            if err:
                self._send_error_response(err, "billing_error", status)
            else:
                self._send_json(res or {}, status)
            return

        if clean_path == "/v1/billing/checkout":
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
        ):
            self.wfile.write(chunk)
            self.wfile.flush()
        self.close_connection = True


def run_gateway_server(host: str = "0.0.0.0", port: int = DEFAULT_PORT) -> None:
    server = ThreadingHTTPServer((host, port), GatewayHandler)
    print(f"ComputeMesh Gateway Server listening on http://{host}:{port}")
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
