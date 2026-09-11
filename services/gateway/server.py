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
from services.portal.passkey_routes import FLEET_ACCOUNT_STORE, PasskeyAuthHandler, session_account_from_headers
from services.portal.routes_downloads import get_download_file_response
from services.portal.routes_payouts import PortalPayoutsHandler


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


def owner_id_for_key(owner_key: str) -> str | None:
    """Derive a stable owner_id from a shared fleet owner key.

    The raw key is never stored; only this derived id is persisted in
    OWNER_ACCOUNT_STORE, so recovering the original key from the database is
    not possible. Requires a non-empty, valid secret key.
    """
    cleaned = str(owner_key or "").strip()
    if not cleaned:
        return None
    return "acct_" + hashlib.sha256(cleaned.encode("utf-8")).hexdigest()[:24]


def _extract_discrete_hardware_fingerprint(n: dict[str, Any]) -> tuple[Any, ...]:
    inv = n.get("inventory", {}) if n else {}
    gpus = inv.get("gpus", []) if inv else []
    from tools.appliance.hardware_detector import is_integrated_display_adapter
    discrete = []
    for g in gpus:
        v = str(g.get("vendor", "")).strip().lower()
        m = str(g.get("model_name", "")).strip()
        vr = int(g.get("vram_bytes", 0) or 0)
        if g.get("healthy", True) and not is_integrated_display_adapter(v, m):
            discrete.append((v, m, vr))
    if discrete:
        discrete.sort()
        return tuple(discrete)
    total_vr = int(inv.get("total_vram_bytes", 0) or 0)
    if total_vr > 0:
        return ("vram_only", total_vr)
    return ()


def _build_fleet_payload(owner_id: str | None, *, include_remote_urls: bool = False) -> dict[str, Any]:
    """Shared node summary for both the raw owner_key fleet API and the
    passkey-session-authenticated portal fleet view (services/portal/passkey_routes.py)."""
    from tools.appliance.hardware_detector import is_integrated_display_adapter

    now = datetime.now(timezone.utc)
    max_age_seconds = 45
    prune_threshold_seconds = 120

    # Auto-prune stale unbound/ephemeral nodes older than 120s during general mesh queries
    if not owner_id:
        stale_pruned = False
        for nid, nd in list(NODE_TELEMETRY_REGISTRY.items()):
            if nd.get("is_peer_relay", False):
                continue
            is_bound = bool(OWNER_ACCOUNT_STORE.owner_for_provider_node(nid))
            if is_bound and not nid.startswith("android-"):
                continue
            up_str = str(nd.get("updated_at", "")).strip()
            if up_str:
                try:
                    ts = datetime.fromisoformat(up_str.replace("Z", "+00:00"))
                    if (now - ts).total_seconds() > prune_threshold_seconds:
                        NODE_TELEMETRY_REGISTRY.pop(nid, None)
                        stale_pruned = True
                except Exception:
                    NODE_TELEMETRY_REGISTRY.pop(nid, None)
                    stale_pruned = True
            else:
                NODE_TELEMETRY_REGISTRY.pop(nid, None)
                stale_pruned = True

        if stale_pruned:
            save_node_telemetry_registry(NODE_TELEMETRY_REGISTRY)

    bound_node_ids = list(OWNER_ACCOUNT_STORE.list_provider_nodes(owner_id)) if owner_id else []
    if not bound_node_ids:
        # Fallback to direct online nodes in telemetry registry
        bound_node_ids = [nid for nid, nd in NODE_TELEMETRY_REGISTRY.items() if not nd.get("is_peer_relay", False)]

    candidates = []
    for node_id in bound_node_ids:
        n = NODE_TELEMETRY_REGISTRY.get(node_id)
        if not n:
            continue
        is_online = False
        updated_at_ts = 0.0
        if not n.get("is_peer_relay", False):
            updated_at_str = str(n.get("updated_at", "")).strip()
            if updated_at_str:
                try:
                    ts = datetime.fromisoformat(updated_at_str.replace("Z", "+00:00"))
                    updated_at_ts = ts.timestamp()
                    if (now - ts).total_seconds() <= max_age_seconds:
                        is_online = True
                except Exception:
                    is_online = False

        # When requesting global/fleet list without specific owner_id filter, only return currently online nodes
        if not owner_id and not is_online:
            continue

        candidates.append({
            "node_id": node_id,
            "data": n,
            "is_online": is_online,
            "updated_at_ts": updated_at_ts,
            "hw_sig": _extract_discrete_hardware_fingerprint(n),
            "auth_token": str(n.get("auth_token", "")).strip(),
            "client_ip": str(n.get("client_ip", "")).strip(),
        })

    # Sort candidates so online nodes and the most recently updated heartbeat comes first
    candidates.sort(key=lambda x: (x["is_online"], x["updated_at_ts"]), reverse=True)

    seen_physical_keys: set[Any] = set()
    deduped_candidates = []
    registry_mutated = False

    for c in candidates:
        token = c["auth_token"]
        ip = c["client_ip"]
        hw = c["hw_sig"]

        phys_key = None
        if token and not token.startswith("peer_relayed_"):
            phys_key = ("token", token)
        elif ip and hw:
            phys_key = ("ip_hw", ip, hw)

        if phys_key and phys_key in seen_physical_keys:
            # Duplicate alias of an existing physical node -> unbind and omit from count
            old_nid = c["node_id"]
            if owner_id:
                try:
                    OWNER_ACCOUNT_STORE.unbind_provider_node(owner_id, old_nid)
                except Exception:
                    pass
            if not c["is_online"]:
                NODE_TELEMETRY_REGISTRY.pop(old_nid, None)
                registry_mutated = True
            continue

        if phys_key:
            seen_physical_keys.add(phys_key)
        deduped_candidates.append(c)

    if registry_mutated:
        save_node_telemetry_registry(NODE_TELEMETRY_REGISTRY)

    nodes_out = []
    total_vram_bytes = 0
    total_tflops = 0.0
    online_count = 0

    for c in deduped_candidates:
        node_id = c["node_id"]
        n = c["data"]
        is_online = c["is_online"]

        inv = n.get("inventory", {}) if n else {}
        telem = n.get("telemetry", {}) if n else {}
        gpus = inv.get("gpus", []) if inv else []
        healthy_gpus = [
            g for g in gpus
            if not is_integrated_display_adapter(g.get("vendor", "unknown"), g.get("model_name", ""))
        ]
        node_vram = sum(g.get("vram_bytes", 0) for g in healthy_gpus)
        if not healthy_gpus and inv.get("total_vram_bytes", 0) > 0:
            node_vram = inv.get("total_vram_bytes", 0)
        node_tflops = float(telem.get("local_compute_tflops", 0.0) or 0.0)

        if is_online:
            online_count += 1
            total_vram_bytes += node_vram
            total_tflops += node_tflops

        node_entry = {
            "node_id": node_id,
            "status": "online" if is_online else "offline",
            "is_online": is_online,
            "vram_gb": round(node_vram / (1024**3), 1),
            "tflops": round(node_tflops, 1) if is_online else 0.0,
            "gpus": [g.get("model_name") for g in gpus] if gpus else [],
            "updated_at": n.get("updated_at") if n else None,
            "dashboard_port": n.get("dashboard_port", 8080) if n else 8080,
            "payout_address": n.get("payout_address", "") if n else "",
            "network": n.get("network", {}) if n else {},
            "candidate_local_urls": _extract_candidate_local_urls(n) if n else [],
        }
        if include_remote_urls and n:
            auth_token = str(n.get("auth_token", "")).strip()
            node_entry["remote_url"] = f"/node/{node_id}?auth={auth_token}" if auth_token else None
        nodes_out.append(node_entry)

    # Sort nodes so online nodes appear first
    nodes_out.sort(key=lambda x: (not x.get("is_online", False), x.get("node_id", "")))

    is_suspended = False
    suspension_reason = None
    banned_at = None
    if owner_id:
        try:
            from services.portal.passkey_routes import FLEET_ACCOUNT_STORE
            if FLEET_ACCOUNT_STORE.is_fleet_banned(owner_id):
                is_suspended = True
                binfo = FLEET_ACCOUNT_STORE.get_fleet_ban_info(owner_id)
                if binfo:
                    suspension_reason = binfo.get("reason")
                    banned_at = binfo.get("banned_at")
        except Exception:
            pass
        if not is_suspended and OWNER_ACCOUNT_STORE.is_owner_banned(owner_id):
            is_suspended = True
            binfo = OWNER_ACCOUNT_STORE.get_owner_ban_info(owner_id)
            if binfo:
                suspension_reason = binfo.get("reason")
                banned_at = binfo.get("banned_at")

    payload_dict = {
        "owner_id": owner_id,
        "total_nodes_bound": len(deduped_candidates),
        "total_nodes_online": online_count,
        "total_vram_gb": round(total_vram_bytes / (1024**3), 1),
        "total_tflops": round(total_tflops, 1),
        "nodes": nodes_out,
        "timestamp": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
    }
    if is_suspended:
        payload_dict["is_suspended"] = True
        payload_dict["suspension_reason"] = suspension_reason or "Administrative suspension"
        payload_dict["banned_at"] = banned_at
    return payload_dict


def _build_ledger_from_env() -> Ledger:
    ledger_path_env = os.environ.get("COMPUTEMESH_LEDGER_PATH")
    path = Path(ledger_path_env) if ledger_path_env else None
    if os.environ.get("COMPUTEMESH_UNIFIED_OWNER_CREDITS", "").strip().lower() in ("1", "true", "yes", "on"):
        from services.billing.owner_gateway_ledger import GatewayOwnerCreditLedger
        return GatewayOwnerCreditLedger(storage_path=path)
    return ThreadSafeLedger(storage_path=path)
from services.billing.stripe_connect import SettlementExecutor, StripeConnectService
from services.billing.stripe_integration import (
    StripePaymentService,
    StripeSessionStore,
    stripe_session_store_path_from_env,
)
from services.common.config import CONFIG
from services.gateway.auth import GatewayAuthManager, extract_bearer_token, resolve_client_ip
from services.gateway.catalog import current_models, resolve_model_id
from services.gateway.dashboard import (
    NODE_TELEMETRY_REGISTRY,
    _extract_candidate_local_urls,
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





def _build_account_store_from_env() -> AccountingStore:
    store_path_env = os.environ.get("COMPUTEMESH_ACCOUNTING_DB_PATH") or os.environ.get("COMPUTEMESH_ACCOUNT_STORE_PATH")
    if store_path_env:
        return AccountingStore(storage_path=Path(store_path_env))
    if sys.platform == "win32":
        p = Path.home() / ".computemesh" / "accounting.db"
    else:
        p = Path("/var/lib/computemesh/accounting.db")
    try:
        p.parent.mkdir(parents=True, exist_ok=True)
    except Exception:
        pass
    return AccountingStore(storage_path=p)


def _build_stripe_service(ledger: Ledger, account_store: AccountingStore | None = None) -> StripePaymentService:
    webhook_secret = os.environ.get("STRIPE_WEBHOOK_SECRET", "").strip()
    stripe_api_key = os.environ.get("STRIPE_API_KEY", "").strip()
    session_store_path_env = stripe_session_store_path_from_env()
    session_store = StripeSessionStore(Path(session_store_path_env)) if session_store_path_env else None
    return StripePaymentService(
        ledger=ledger,
        webhook_secret=webhook_secret,
        stripe_api_key=stripe_api_key,
        session_store=session_store,
        webhook_event_store=account_store,
    )


def _stripe_readiness(service: StripePaymentService) -> dict[str, Any]:
    """Return non-sensitive Stripe readiness facts for operational health checks."""
    api_key = service.stripe_api_key
    mode = "live" if api_key.startswith("sk_live_") else "test" if api_key.startswith("sk_test_") else "unconfigured"
    webhook_configured = bool(service._webhook_secrets())
    session_store_configured = service.session_store is not None
    if mode == "unconfigured":
        status = "not_configured"
    elif session_store_configured and webhook_configured:
        status = "ready"
    else:
        status = "degraded"
    return {
        "status": status,
        "mode": mode,
        "checkout_configured": mode != "unconfigured" and session_store_configured,
        "webhook_configured": webhook_configured,
        "session_store_configured": session_store_configured,
    }


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
    account_store: AccountingStore = _build_account_store_from_env()
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
    payouts_handler: PortalPayoutsHandler = PortalPayoutsHandler(ledger=ledger, account_store=account_store)

    @classmethod
    def sync_subsystems(cls) -> None:
        """Synchronizes sub-handlers when class-level dependencies are modified."""
        cls.auth_manager = GatewayAuthManager(ledger=cls.ledger, teaser_manager=cls.teaser_manager, api_keys=getattr(cls, "api_keys", {}), owner_account_store=OWNER_ACCOUNT_STORE)
        cls.billing_routes = BillingRoutesHandler(ledger=cls.ledger, stripe_svc=cls.stripe_svc, auth_manager=cls.auth_manager)
        try:
            cls.provider_routes = ProviderRoutesHandler(account_store=cls.account_store, settlement_executor=cls.settlement_executor, auth_manager=cls.auth_manager, ledger=cls.ledger)
        except Exception:
            pass
        try:
            cls.payouts_handler = PortalPayoutsHandler(ledger=cls.ledger, account_store=cls.account_store)
        except Exception:
            pass
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
        body = json.dumps(payload, indent=2, ensure_ascii=False).encode("utf-8")
        self.send_response(HTTPStatus.TOO_MANY_REQUESTS)
        self.send_header("Content-Type", "application/json; charset=utf-8")
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
        body = json.dumps(data, indent=2, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
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
            self._send_json({
                "status": "healthy",
                "service": "computemesh-gateway",
                "stripe": _stripe_readiness(self.stripe_svc),
            })
            return

        if clean_path in ("/health", "/webui/health", "/api/health", "/v1/health"):
            self._send_json({
                "status": "ok",
                "slots_idle": 1,
                "slots_processing": 0,
                "service": "computemesh-gateway",
                "stripe": _stripe_readiness(self.stripe_svc),
            })
            return

        if clean_path in ("/props", "/webui/props", "/api/props", "/v1/props", "/api/v1/props"):
            self._handle_props()
            return

        if clean_path in ("/slots", "/webui/slots", "/api/slots", "/v1/slots"):
            self._handle_slots()
            return

        if clean_path.startswith("/node/"):
            node_rel = clean_path.removeprefix("/node/").strip("/")
            parts = node_rel.split("/", 1)
            node_id = parts[0].strip()
            sub_path = "/" + parts[1] if len(parts) > 1 else ""
            auth_token = query.get("auth", [""])[0].strip()

            if sub_path in ("/props", "/webui/props", "/api/props", "/v1/props"):
                self._handle_props()
                return
            if sub_path in ("/slots", "/webui/slots", "/api/slots", "/v1/slots"):
                self._handle_slots()
                return
            if sub_path in ("/v1/models", "/models", "/webui/models", "/api/models", "/api/tags", "/api/v1/models"):
                self._handle_models()
                return
            if sub_path in ("/api/version", "/version"):
                self._send_json({"version": "1.2.156", "node_id": node_id})
                return
            if sub_path in ("/api/status", "/status"):
                node_data = NODE_TELEMETRY_REGISTRY.get(node_id, {})
                self._send_json(node_data)
                return

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

        if clean_path in ("/models/sse", "/webui/models/sse", "/v1/models/sse"):
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", "text/event-stream; charset=utf-8")
            self.send_header("Cache-Control", "no-cache")
            self.send_header("Connection", "close")
            for h_name, h_val in SECURITY_HEADERS.items():
                self.send_header(h_name, h_val)
            self.end_headers()
            self.wfile.write(b'data: {"status": "ok", "action": "ready"}\n\n')
            self.wfile.flush()
            self.close_connection = True
            return

        if clean_path in ("/models/load", "/webui/models/load", "/models/unload", "/webui/models/unload"):
            self._send_json({"status": "ok", "message": "model ready"})
            return

        if clean_path in ("/v1/models", "/models", "/webui/models", "/webui/v1/models", "/api/models", "/api/v1/models"):
            self._handle_models()
            return

        if clean_path in ("/api/tags", "/api/v1/tags"):
            self._handle_ollama_tags()
            return

        if clean_path in ("/api/portal/qr", "/api/v1/qr"):
            query_params = urllib.parse.parse_qs(parsed_path.query)
            text = query_params.get("data", [""])[0].strip() or query_params.get("text", [""])[0].strip()
            if not text:
                text = "https://mesh.inetconnector.com/downloads/ComputeMesh-Android.apk"
            try:
                import io
                import qrcode
                import qrcode.image.svg
                factory = qrcode.image.svg.SvgPathImage
                img = qrcode.make(text, image_factory=factory, box_size=8, border=2)
                bio = io.BytesIO()
                img.save(bio)
                svg_bytes = bio.getvalue()
                self.send_response(HTTPStatus.OK)
                self.send_header("Content-Type", "image/svg+xml")
                self.send_header("Content-Length", str(len(svg_bytes)))
                self.send_header("Access-Control-Allow-Origin", "*")
                self.send_header("Cache-Control", "public, max-age=3600")
                self.end_headers()
                self.wfile.write(svg_bytes)
            except Exception as exc:
                self._send_error_response(f"QR generation failed: {exc}", "internal_error", HTTPStatus.INTERNAL_SERVER_ERROR)
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
                    if candidate.startswith("inet-") or candidate.startswith("ok_") or candidate.startswith("owner_") or candidate.startswith("cm_owner_") or candidate.startswith("owk_"):
                        owner_key = candidate
            owner_id = owner_id_for_key(owner_key) if owner_key else None
            self._send_json(_build_fleet_payload(owner_id, include_remote_urls=True))
            return

        if clean_path in ("/v1/mcp/tools", "/api/v1/mcp/tools", "/mcp/tools"):
            tools = self.inference_engine.tool_registry.get_openai_tools(is_owner=True)
            self._send_json({"object": "list", "data": tools})
            return

        if clean_path == "/api/auth/me":
            account = session_account_from_headers(self.headers)
            if account is None:
                self._send_json({"error": "not signed in"}, HTTPStatus.UNAUTHORIZED)
                return
            self._send_json({"account_id": account.account_id, "email": account.email, "owner_key": account.owner_key})
            return

        if clean_path == "/api/auth/passkeys":
            data, status, cookie = self.passkey_handler.list_passkeys(self.headers)
            self._send_json(data, status, extra_headers={"Set-Cookie": cookie} if cookie else None)
            return

        if clean_path == "/api/portal/fleet/audit_log":
            data, status, cookie = self.passkey_handler.get_audit_log(self.headers)
            self._send_json(data, status, extra_headers={"Set-Cookie": cookie} if cookie else None)
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
                        if candidate.startswith("inet-") or candidate.startswith("ok_") or candidate.startswith("owner_") or candidate.startswith("cm_owner_") or candidate.startswith("owk_"):
                            owner_key = candidate
            if not owner_key and account is None:
                self._send_json({"error": "not signed in"}, HTTPStatus.UNAUTHORIZED)
                return
            facc = FLEET_ACCOUNT_STORE.get_account_by_owner_key(owner_key) if owner_key else None
            facc_id = facc.account_id if facc else (account.account_id if account else None)
            derived_owner_id = owner_id_for_key(owner_key) if owner_key else None
            owner_id = facc_id or derived_owner_id
            payload = _build_fleet_payload(derived_owner_id or facc_id, include_remote_urls=True)
            is_banned = False
            binfo = None
            for check_id in filter(None, [facc_id, derived_owner_id, owner_id]):
                if FLEET_ACCOUNT_STORE.is_fleet_banned(check_id):
                    is_banned = True
                    binfo = FLEET_ACCOUNT_STORE.get_fleet_ban_info(check_id)
                    break
            if is_banned and binfo:
                payload["is_suspended"] = True
                payload["suspension_reason"] = binfo.get("reason", "Administrative suspension")
                payload["banned_at"] = binfo.get("banned_at")
            self._send_json(payload)
            return

        if clean_path == "/api/portal/fleet/payouts":
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
                        if candidate.startswith("inet-") or candidate.startswith("ok_") or candidate.startswith("owner_") or candidate.startswith("cm_owner_") or candidate.startswith("owk_"):
                            owner_key = candidate
            if not owner_key and account is None:
                self._send_json({"error": "not signed in"}, HTTPStatus.UNAUTHORIZED)
                return
            owner_id = owner_id_for_key(owner_key)
            if not owner_id:
                self._send_json({"error": "invalid owner key"}, HTTPStatus.UNAUTHORIZED)
                return
            data = self.payouts_handler.get_payout_overview(owner_id)
            self._send_json(data)
            return

        if clean_path in ("/api/portal/fleet/mcp_settings", "/api/v1/mesh/fleet/mcp_settings"):
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
                        if candidate.startswith("inet-") or candidate.startswith("ok_") or candidate.startswith("owner_") or candidate.startswith("cm_owner_") or candidate.startswith("owk_"):
                            owner_key = candidate
            if not owner_key and account is None:
                self._send_json({"error": "not signed in"}, HTTPStatus.UNAUTHORIZED)
                return
            owner_id = owner_id_for_key(owner_key)
            if not owner_id:
                self._send_json({"error": "invalid owner key"}, HTTPStatus.UNAUTHORIZED)
                return
            disabled = FLEET_ACCOUNT_STORE.get_mcp_disabled_tools(owner_id)
            all_tools = [t.name for t in self.inference_engine.tool_registry.list_tools(is_owner=True)]
            enabled_tools = [t for t in all_tools if t not in disabled]
            self._send_json({
                "owner_id": owner_id,
                "disabled_tools": disabled,
                "enabled_tools": enabled_tools,
                "total_tools": len(all_tools),
            })
            return

        if clean_path in ("/api/admin/fleet/banned", "/api/portal/fleet/admin/banned"):
            master_key_header = self.headers.get("X-Master-Killswitch-Key", "").strip()
            auth_hdr = self.headers.get("Authorization", "").strip()
            candidate = master_key_header
            if not candidate and auth_hdr.startswith("Bearer "):
                candidate = auth_hdr[7:].strip()
            master_env_key = os.environ.get("COMPUTEMESH_MASTER_ADMIN_KEY", "").strip()
            admin_env_key = os.environ.get("COMPUTEMESH_ADMIN_KEY", "").strip()
            is_master = bool(
                (master_env_key and candidate and hmac.compare_digest(candidate, master_env_key))
                or (admin_env_key and candidate and len(admin_env_key) >= 24 and hmac.compare_digest(candidate, admin_env_key))
            )
            if not is_master:
                self._send_json({"error": "Admin/Master-Berechtigung erforderlich"}, HTTPStatus.FORBIDDEN)
                return
            banned = FLEET_ACCOUNT_STORE.list_banned_fleets(active_only=False)
            self._send_json({"status": "ok", "banned_fleets": banned, "total": len(banned)})
            return

        if clean_path in ("/api/portal/fleet/killswitch/status", "/api/killswitch/status"):
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
                        if candidate.startswith("inet-") or candidate.startswith("ok_") or candidate.startswith("owner_") or candidate.startswith("cm_owner_") or candidate.startswith("owk_"):
                            owner_key = candidate
            owner_id = owner_id_for_key(owner_key) if owner_key else None
            from runtime.safety.dead_mans_switch import get_lease_guard
            guard = get_lease_guard()
            st = guard.get_status(owner_id=owner_id)
            self._send_json(st)
            return

        if clean_path in (
            "/api/portal/download/ollama-starter",
            "/api/portal/download/ollama-reset",
            "/download/ollama-starter",
            "/download/ollama-reset",
            "/api/v1/download/ollama-starter",
            "/api/v1/download/ollama-reset",
        ):
            account = session_account_from_headers(self.headers)
            owner_key = ""
            if account is not None:
                owner_key = account.owner_key
            else:
                owner_key = (
                    query.get("key", [""])[0].strip()
                    or query.get("owner_key", [""])[0].strip()
                    or self.headers.get("X-Owner-Key", "").strip()
                )
                if not owner_key:
                    auth_hdr = self.headers.get("Authorization", "").strip()
                    if auth_hdr.startswith("Bearer "):
                        candidate = auth_hdr[7:].strip()
                        if candidate.startswith("inet-") or candidate.startswith("ok_") or candidate.startswith("owner_") or candidate.startswith("cm_owner_") or candidate.startswith("owk_"):
                            owner_key = candidate

            os_target = query.get("os", ["windows"])[0].strip()
            script_type = "reset" if "reset" in clean_path else "starter"
            content, filename, content_type = get_download_file_response(
                script_type=script_type,
                os_target=os_target,
                owner_key=owner_key,
            )
            body = content.encode("utf-8")
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", f"{content_type}; charset=utf-8")
            self.send_header("Content-Disposition", f'attachment; filename="{filename}"')
            self.send_header("Content-Length", str(len(body)))
            for h_name, h_val in SECURITY_HEADERS.items():
                self.send_header(h_name, h_val)
            self.end_headers()
            self.wfile.write(body)
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

        if clean_path in ("/v1/billing/balance", "/api/v1/billing/balance", "/api/billing/balance", "/billing/balance"):
            res, err, status = self.billing_routes.handle_get_balance(self.headers)
            if err:
                self._send_error_response(err, "billing_error", status)
            else:
                self._send_json(res or {}, status)
            return

        if clean_path in ("/v1/billing/webhook", "/api/v1/billing/webhook", "/api/billing/webhook", "/billing/webhook"):
            self._send_json({"status": "ok", "message": "Stripe Webhook Endpoint Active"})
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

        if clean_path in ("/v1/billing/webhook", "/api/v1/billing/webhook", "/api/billing/webhook", "/billing/webhook"):
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

        self._is_node_tunnel = False
        if clean_path.startswith("/node/"):
            self._is_node_tunnel = True
            node_rel = clean_path.removeprefix("/node/").strip("/")
            parts = node_rel.split("/", 1)
            if len(parts) > 1:
                clean_path = "/" + parts[1]

        if clean_path == "/api/auth/register/begin":
            data, status, cookie = self.passkey_handler.register_begin(body, self.headers, self.client_address)
            self._send_json(data, status, extra_headers={"Set-Cookie": cookie} if cookie else None)
            return

        if clean_path == "/api/auth/register/complete":
            data, status, cookie = self.passkey_handler.register_complete(body, self.headers, self.client_address)
            self._send_json(data, status, extra_headers={"Set-Cookie": cookie} if cookie else None)
            return

        if clean_path == "/api/auth/login/begin":
            data, status, cookie = self.passkey_handler.login_begin(body, self.headers, self.client_address)
            self._send_json(data, status, extra_headers={"Set-Cookie": cookie} if cookie else None)
            return

        if clean_path == "/api/auth/login/complete":
            data, status, cookie = self.passkey_handler.login_complete(body, self.headers, self.client_address)
            self._send_json(data, status, extra_headers={"Set-Cookie": cookie} if cookie else None)
            return

        if clean_path == "/api/auth/magic_link/request":
            data, status, cookie = self.passkey_handler.request_magic_link(body, self.headers, self.client_address)
            self._send_json(data, status, extra_headers={"Set-Cookie": cookie} if cookie else None)
            return

        if clean_path == "/api/auth/magic_link/verify":
            data, status, cookie = self.passkey_handler.verify_magic_link(body, self.headers, self.client_address)
            self._send_json(data, status, extra_headers={"Set-Cookie": cookie} if cookie else None)
            return

        if clean_path == "/api/auth/passkeys/delete":
            data, status, cookie = self.passkey_handler.delete_passkey(self.headers, body, self.client_address)
            self._send_json(data, status, extra_headers={"Set-Cookie": cookie} if cookie else None)
            return

        if clean_path == "/api/auth/passkeys/rename":
            data, status, cookie = self.passkey_handler.rename_passkey(self.headers, body)
            self._send_json(data, status, extra_headers={"Set-Cookie": cookie} if cookie else None)
            return

        if clean_path == "/api/portal/fleet/enrollment_token":
            data, status, cookie = self.passkey_handler.create_enrollment_token(self.headers)
            self._send_json(data, status, extra_headers={"Set-Cookie": cookie} if cookie else None)
            return

        if clean_path in ("/api/auth/owner_key/rotate", "/api/portal/owner_key/rotate"):
            data, status, cookie = self.passkey_handler.rotate_owner_key(self.headers, body, self.client_address)
            self._send_json(data, status, extra_headers={"Set-Cookie": cookie} if cookie else None)
            return

        if clean_path in ("/api/auth/email/update", "/api/portal/auth/email/update"):
            data, status, cookie = self.passkey_handler.update_email(self.headers, body, self.client_address)
            self._send_json(data, status, extra_headers={"Set-Cookie": cookie} if cookie else None)
            return

        if clean_path in ("/api/portal/fleet/mcp_settings", "/api/v1/mesh/fleet/mcp_settings"):
            account = session_account_from_headers(self.headers)
            owner_key = ""
            if account is not None:
                owner_key = account.owner_key
            else:
                owner_key = str(body.get("owner_key", "")).strip() or query.get("owner_key", [""])[0].strip() or self.headers.get("X-Owner-Key", "").strip()
                if not owner_key:
                    auth_hdr = self.headers.get("Authorization", "").strip()
                    if auth_hdr.startswith("Bearer "):
                        candidate = auth_hdr[7:].strip()
                        if candidate.startswith("inet-") or candidate.startswith("ok_") or candidate.startswith("owner_") or candidate.startswith("cm_owner_") or candidate.startswith("owk_"):
                            owner_key = candidate
            if not owner_key and account is None:
                self._send_json({"error": "not signed in"}, HTTPStatus.UNAUTHORIZED)
                return
            owner_id = owner_id_for_key(owner_key)
            if not owner_id:
                self._send_json({"error": "invalid owner key"}, HTTPStatus.UNAUTHORIZED)
                return
            disabled_tools = body.get("disabled_tools", [])
            if not isinstance(disabled_tools, list):
                disabled_tools = []
            FLEET_ACCOUNT_STORE.set_mcp_disabled_tools(owner_id, disabled_tools)
            OWNER_ACCOUNT_STORE.set_mcp_disabled_tools(owner_id, disabled_tools)
            self._send_json({
                "status": "ok",
                "owner_id": owner_id,
                "disabled_tools": disabled_tools,
            })
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

            client_ip = resolve_client_ip(self.headers, getattr(self, "client_address", None))
            sys.stderr.write(f"[HEARTBEAT] node_id={node_id} client={client_ip}\n")
            sys.stderr.flush()

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

                owner_authorized = False
                sent_owner_key_pre = str(body.get("owner_key", "")).strip()
                if sent_owner_key_pre:
                    sender_owner = owner_id_for_key(sent_owner_key_pre)
                    existing_owner = existing_node.get("owner_id")
                    if sender_owner and (not existing_owner or existing_owner == sender_owner):
                        owner_authorized = True

                is_dummy_override = (
                    existing_node.get("is_peer_relay", False)
                    or (int(existing_node.get("inventory", {}).get("total_gpus", 0) or 0) == 0 and int(body.get("inventory", {}).get("total_gpus", 0) or 0) > 0)
                )

                if expected_token and not is_stale and not owner_authorized and not is_dummy_override and not hmac.compare_digest(auth_token, expected_token):
                    self._send_error_response("Unauthorized: auth_token mismatch for active node", "unauthorized", HTTPStatus.UNAUTHORIZED)
                    return

            sent_owner_key = str(body.get("owner_key", "")).strip()
            resolved_owner_key = FLEET_ACCOUNT_STORE.resolve_latest_owner_key(sent_owner_key) if sent_owner_key else ""
            active_owner_key = resolved_owner_key or sent_owner_key
            key_rotated = bool(resolved_owner_key and resolved_owner_key != sent_owner_key)

            owner_binding_error: str | None = None
            owner_id = owner_id_for_key(active_owner_key)
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

            # If the same physical client (same auth_token) renamed its node_id, retire the previous alias
            for old_id, old_node in list(NODE_TELEMETRY_REGISTRY.items()):
                if old_id != node_id and old_node.get("auth_token") == auth_token and not old_node.get("is_peer_relay", False):
                    NODE_TELEMETRY_REGISTRY.pop(old_id, None)
                    if owner_id:
                        OWNER_ACCOUNT_STORE.unbind_provider_node(owner_id, old_id)

            now_iso = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
            existing_tokens = int(existing_node.get("telemetry", {}).get("tokens_processed", 0) or 0) if existing_node else 0
            incoming_tokens = int(body.get("telemetry", {}).get("tokens_processed", 0) or 0)
            final_tokens = max(existing_tokens, incoming_tokens)

            telemetry_data = body.get("telemetry", {})
            telemetry_data["tokens_processed"] = final_tokens
            telemetry_data["earnings_cm"] = final_tokens

            dash_port = int(body.get("dashboard_port") or body.get("network", {}).get("dashboard_port") or 8080)
            NODE_TELEMETRY_REGISTRY[node_id] = {
                "node_id": node_id,
                "auth_token": auth_token,
                "owner_id": owner_id,
                "client_ip": str(client_ip),
                "dashboard_port": dash_port,
                "network": body.get("network", {}),
                "local_ip": str(body.get("local_ip", "")).strip(),
                "inventory": body.get("inventory", {}),
                "telemetry": telemetry_data,
                "global_mesh": body.get("global_mesh", {}),
                "software": body.get("software", {}),
                "updated_at": now_iso,
            }

            # Register discovered cluster peers (e.g. LAN miners or secondary appliances)
            # Deliberately do not set updated_at=now_iso for relayed peers so they do not falsely appear as direct online nodes
            gm = body.get("global_mesh", {})
            for peer in gm.get("nodes", []):
                p_id = str(peer.get("node_id", "")).strip()
                p_vram_gb = float(peer.get("vram_gb", 0.0) or 0.0)
                if p_id and p_id != node_id and not peer.get("is_local", False) and p_id not in ("windows-laptop", "unnamed-node", "test-node-custom", "mifcom") and p_vram_gb > 0:
                    p_vram_bytes = int(p_vram_gb * 1024 * 1024 * 1024)
                    p_tflops = float(peer.get("tflops", 0.0) or 0.0)
                    p_gpus_cnt = int(peer.get("gpus_count", 1) or 1)

                    if p_id not in NODE_TELEMETRY_REGISTRY:
                        NODE_TELEMETRY_REGISTRY[p_id] = {
                            "node_id": p_id,
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
                            "updated_at": "",
                        }

            save_node_telemetry_registry(NODE_TELEMETRY_REGISTRY)
            resp = {
                "status": "ok",
                "message": "heartbeat registered",
                "node_id": node_id,
                "owner_key": active_owner_key,
                "key_rotated": key_rotated,
                "tokens_processed": final_tokens,
                "earnings_cm": final_tokens,
                "earnings_usd": round(final_tokens * (0.75 / 1_000_000.0), 6),
            }
            if owner_binding_error:
                resp["owner_binding_error"] = owner_binding_error
            self._send_json(resp)
            return

        if clean_path in ("/api/v1/node/sync_key", "/api/node/sync_key"):
            node_id = str(body.get("node_id", "")).strip()
            auth_token = str(body.get("auth_token", "")).strip()
            sent_owner_key = str(body.get("owner_key", "")).strip()
            if not node_id:
                self._send_error_response("Valid node_id is required", "invalid_request_error", HTTPStatus.BAD_REQUEST)
                return
            if not auth_token:
                self._send_error_response("auth_token is required", "unauthorized", HTTPStatus.UNAUTHORIZED)
                return

            resolved = FLEET_ACCOUNT_STORE.resolve_latest_owner_key(sent_owner_key) if sent_owner_key else ""
            active_key = resolved or sent_owner_key
            key_rotated = bool(resolved and resolved != sent_owner_key)
            self._send_json({
                "status": "ok",
                "node_id": node_id,
                "owner_key": active_key,
                "key_rotated": key_rotated,
            })
            return

        if clean_path in ("/api/portal/fleet/unbind_node", "/api/v1/mesh/fleet/unbind_node"):
            node_id = str(body.get("node_id", "")).strip()
            if not node_id:
                self._send_error_response("node_id is required", "invalid_request", HTTPStatus.BAD_REQUEST)
                return

            account = session_account_from_headers(self.headers)
            owner_key = str(body.get("owner_key", "")).strip()
            if account is not None:
                owner_id = owner_id_for_key(account.owner_key)
            elif owner_key:
                owner_id = owner_id_for_key(owner_key)
            else:
                owner_id = owner_id_for_key("")

            unbound = OWNER_ACCOUNT_STORE.unbind_provider_node(owner_id, node_id)
            if node_id in NODE_TELEMETRY_REGISTRY:
                NODE_TELEMETRY_REGISTRY.pop(node_id, None)
                save_node_telemetry_registry(NODE_TELEMETRY_REGISTRY)

            self._send_json({"status": "ok", "unbound": unbound, "node_id": node_id})
            return

        if clean_path in (
            "/api/portal/fleet/payouts/onboard",
            "/api/portal/fleet/payouts/refresh",
            "/api/portal/fleet/payouts/settle",
        ):
            account = session_account_from_headers(self.headers)
            owner_key = ""
            if account is not None:
                owner_key = account.owner_key
            else:
                owner_key = str(body.get("owner_key", "")).strip() or self.headers.get("X-Owner-Key", "").strip()
                if not owner_key:
                    auth_hdr = self.headers.get("Authorization", "").strip()
                    if auth_hdr.startswith("Bearer "):
                        candidate = auth_hdr[7:].strip()
                        if candidate.startswith("inet-") or candidate.startswith("ok_") or candidate.startswith("owner_") or candidate.startswith("cm_owner_") or candidate.startswith("owk_"):
                            owner_key = candidate
            if not owner_key and account is None:
                self._send_json({"error": "not signed in"}, HTTPStatus.UNAUTHORIZED)
                return
            owner_id = owner_id_for_key(owner_key)
            if not owner_id:
                self._send_json({"error": "invalid owner key"}, HTTPStatus.UNAUTHORIZED)
                return

            if clean_path == "/api/portal/fleet/payouts/onboard":
                email = (account.email if account else "") or str(body.get("email", "")).strip()
                country = str(body.get("country", "DE")).strip().upper()
                return_url = str(body.get("return_url", "https://mesh.inetconnector.com/fleet?stripe=return")).strip()
                refresh_url = str(body.get("refresh_url", "https://mesh.inetconnector.com/fleet?stripe=refresh")).strip()
                try:
                    data = self.payouts_handler.start_onboarding(
                        owner_id=owner_id,
                        email=email,
                        country=country,
                        return_url=return_url,
                        refresh_url=refresh_url,
                    )
                    self._send_json(data)
                except Exception as exc:
                    from services.billing.stripe_connect import is_stripe_connect_platform_activation_error
                    status = HTTPStatus.SERVICE_UNAVAILABLE if is_stripe_connect_platform_activation_error(exc) else HTTPStatus.BAD_REQUEST
                    self._send_json({"error": str(exc)}, status)
                return

            if clean_path == "/api/portal/fleet/payouts/refresh":
                data = self.payouts_handler.refresh_status(owner_id)
                self._send_json(data)
                return

            if clean_path == "/api/portal/fleet/payouts/settle":
                amount_micro = body.get("amount_micro_units")
                try:
                    data = self.payouts_handler.execute_settlement(owner_id, amount_micro)
                    if "error" in data:
                        self._send_json(data, HTTPStatus.BAD_REQUEST)
                    else:
                        self._send_json(data)
                except Exception as exc:
                    self._send_json({"error": str(exc)}, HTTPStatus.BAD_REQUEST)
                return

        # Master Admin Fleet Ban & Unban Routes
        if clean_path in (
            "/api/admin/fleet/ban",
            "/api/portal/fleet/admin/ban",
            "/api/admin/fleet/unban",
            "/api/portal/fleet/admin/unban",
        ):
            master_key_header = self.headers.get("X-Master-Killswitch-Key", "").strip()
            auth_hdr_raw = self.headers.get("Authorization", "").strip()
            candidate = master_key_header
            if not candidate and auth_hdr_raw.startswith("Bearer "):
                candidate = auth_hdr_raw[7:].strip()
            master_env_key = os.environ.get("COMPUTEMESH_MASTER_ADMIN_KEY", "").strip()
            admin_env_key = os.environ.get("COMPUTEMESH_ADMIN_KEY", "").strip()
            is_master = bool(
                (master_env_key and candidate and hmac.compare_digest(candidate, master_env_key))
                or (admin_env_key and candidate and len(admin_env_key) >= 24 and hmac.compare_digest(candidate, admin_env_key))
            )
            if not is_master:
                self._send_json({
                    "error": "Berechtigungs-Schutz: Nur der Master-Administrator (Plattform-Inhaber) darf Flotten dauerhaft sperren oder entsperren."
                }, HTTPStatus.FORBIDDEN)
                return

            target_owner_id = str(body.get("owner_id", "")).strip()
            if not target_owner_id:
                self._send_json({"error": "owner_id parameter is required"}, HTTPStatus.BAD_REQUEST)
                return

            if "ban" in clean_path and not clean_path.endswith("unban"):
                reason = str(body.get("reason", "Administrative suspension")).strip()
                banned_by = str(body.get("banned_by", "master_admin")).strip()
                ban_result = FLEET_ACCOUNT_STORE.ban_fleet(target_owner_id, reason=reason, banned_by=banned_by)
                OWNER_ACCOUNT_STORE.ban_owner(target_owner_id, reason=reason, banned_by=banned_by)
                self._send_json({
                    "status": "ok",
                    "action": "ban",
                    "owner_id": target_owner_id,
                    "message": f"Flotte '{target_owner_id}' wurde durch den Master-Administrator dauerhaft gesperrt.",
                    "ban": ban_result,
                }, HTTPStatus.OK)
                return

            if "unban" in clean_path:
                reason = str(body.get("reason", "Administrative reactivation")).strip()
                unbanned_by = str(body.get("unbanned_by", "master_admin")).strip()
                unbanned = FLEET_ACCOUNT_STORE.unban_fleet(target_owner_id, reason=reason, unbanned_by=unbanned_by)
                OWNER_ACCOUNT_STORE.unban_owner(target_owner_id, reason=reason, unbanned_by=unbanned_by)
                self._send_json({
                    "status": "ok",
                    "action": "unban",
                    "owner_id": target_owner_id,
                    "unbanned": unbanned,
                    "message": f"Flotte '{target_owner_id}' wurde erfolgreich reaktiviert. Normalbetrieb ist wieder freigegeben.",
                }, HTTPStatus.OK)
                return

        # Kill Switch Multi-Tenant & Master Endpoints
        if clean_path in (
            "/api/portal/fleet/killswitch/trigger",
            "/api/killswitch/trigger",
            "/api/portal/fleet/killswitch/reset",
            "/api/killswitch/reset",
            "/api/portal/fleet/killswitch/renew",
            "/api/killswitch/renew",
        ):
            account = session_account_from_headers(self.headers)
            owner_key = ""
            if account is not None:
                owner_key = account.owner_key
            else:
                owner_key = str(body.get("owner_key", "")).strip() or self.headers.get("X-Owner-Key", "").strip()
                if not owner_key:
                    auth_hdr = self.headers.get("Authorization", "").strip()
                    if auth_hdr.startswith("Bearer "):
                        candidate = auth_hdr[7:].strip()
                        if candidate.startswith("inet-") or candidate.startswith("ok_") or candidate.startswith("owner_") or candidate.startswith("cm_owner_") or candidate.startswith("owk_"):
                            owner_key = candidate

            owner_id = owner_id_for_key(owner_key) if owner_key else (account.account_id if account else None)
            from runtime.safety.dead_mans_switch import get_lease_guard
            guard = get_lease_guard()

            master_key_header = self.headers.get("X-Master-Killswitch-Key", "").strip()
            auth_hdr_raw = self.headers.get("Authorization", "").strip()
            master_cand = master_key_header
            if not master_cand and auth_hdr_raw.startswith("Bearer "):
                master_cand = auth_hdr_raw[7:].strip()
            master_env_key = os.environ.get("COMPUTEMESH_MASTER_ADMIN_KEY", "").strip()
            admin_env_key = os.environ.get("COMPUTEMESH_ADMIN_KEY", "").strip()
            is_master = bool(
                (master_env_key and master_cand and hmac.compare_digest(master_cand, master_env_key))
                or (admin_env_key and master_cand and len(admin_env_key) >= 24 and hmac.compare_digest(master_cand, admin_env_key))
            )

            req_scope = str(body.get("scope", "fleet")).lower().strip()
            reason = str(body.get("reason", "Emergency Operator Action"))

            if "trigger" in clean_path:
                if req_scope in ("global", "platform", "cluster"):
                    if not is_master:
                        if owner_id:
                            guard.trip_fleet(owner_id, reason=reason)
                        self._send_json({
                            "status": "forbidden",
                            "scope": "fleet" if owner_id else "unauthorized",
                            "owner_id": owner_id,
                            "error": "Berechtigungs-Schutz: Ein Flottenbetreiber darf niemals das Gesamtsystem zum Einsturz bringen oder stoppen. Der globale Plattform-Not-Aus ist strikt dem Plattform-Inhaber (inetconnector / Stripe Account Owner) vorbehalten.",
                            "message": "Deine eigene Flotte wurde isoliert und gestoppt. Das Restsystem und alle anderen Provider laufen 100% unterbrechungsfrei weiter.",
                            "guard": guard.get_status(owner_id=owner_id),
                        }, HTTPStatus.FORBIDDEN)
                        return

                    guard.trip(reason=reason, is_master=True)
                    self._send_json({
                        "status": "global_tripped",
                        "scope": "global",
                        "message": f"Globaler Plattform-Not-Aus durch Plattform-Inhaber ausgelöst: {reason}",
                        "guard": guard.get_status(),
                    }, HTTPStatus.OK)
                    return

                if not owner_id:
                    self._send_json({"error": "Authentifizierung als Flottenbetreiber erforderlich"}, HTTPStatus.UNAUTHORIZED)
                    return

                trip_res = guard.trip_fleet(owner_id, reason=reason)
                self._send_json({
                    "status": "ok",
                    "scope": "fleet",
                    "owner_id": owner_id,
                    "message": f"Flotten-Not-Aus aktiviert für Flotte '{owner_id}'. Alle Rechenknoten deiner Flotte wurden angehalten.",
                    "fleet_status": trip_res,
                    "guard": guard.get_status(owner_id=owner_id),
                }, HTTPStatus.OK)
                return

            if "reset" in clean_path:
                if req_scope in ("global", "platform", "cluster"):
                    if not is_master:
                        self._send_json({
                            "error": "Berechtigungs-Schutz: Nur der Plattform-Inhaber (inetconnector / Stripe Account Owner) darf den globalen Not-Aus zurücksetzen."
                        }, HTTPStatus.FORBIDDEN)
                        return
                    guard.reset(reason=reason)
                    self._send_json({
                        "status": "ok",
                        "scope": "global",
                        "message": f"Globaler Plattform-Not-Aus zurückgesetzt: {reason}",
                        "guard": guard.get_status(),
                    }, HTTPStatus.OK)
                    return

                if not owner_id:
                    self._send_json({"error": "Authentifizierung als Flottenbetreiber erforderlich"}, HTTPStatus.UNAUTHORIZED)
                    return

                guard.reset_fleet(owner_id, reason=reason)
                self._send_json({
                    "status": "ok",
                    "scope": "fleet",
                    "owner_id": owner_id,
                    "message": f"Flotten-Not-Aus für Flotte '{owner_id}' aufgehoben. Normaler Inferenzbetrieb wieder freigegeben.",
                    "guard": guard.get_status(owner_id=owner_id),
                }, HTTPStatus.OK)
                return

            if "renew" in clean_path:
                if guard.is_tripped:
                    self._send_json({"error": f"Globaler Not-Aus ist aktiv ({guard.trip_reason})"}, HTTPStatus.SERVICE_UNAVAILABLE)
                    return
                if owner_id and guard.is_fleet_tripped(owner_id):
                    self._send_json({"error": f"Flotte '{owner_id}' ist im Not-Aus ({guard.get_fleet_trip_reason(owner_id)})"}, HTTPStatus.SERVICE_UNAVAILABLE)
                    return
                self._send_json({
                    "status": "ok",
                    "message": "Authorization lease active",
                    "guard": guard.get_status(owner_id=owner_id),
                }, HTTPStatus.OK)
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

        if clean_path in ("/api/v1/contact", "/api/contact", "/v1/contact"):
            from services.portal.mail_dispatcher import send_contact_inquiry
            name = str(body.get("name", "")).strip()
            email = str(body.get("email", "")).strip()
            topic = str(body.get("topic", "developer")).strip()
            message = str(body.get("message", "")).strip()

            if not name or len(name) < 2:
                self._send_error_response("Name is required (min 2 characters)", "invalid_request_error", HTTPStatus.BAD_REQUEST)
                return
            if not email or "@" not in email or "." not in email:
                self._send_error_response("Valid email address is required", "invalid_request_error", HTTPStatus.BAD_REQUEST)
                return
            if not message or len(message) < 3:
                self._send_error_response("Message is required (min 3 characters)", "invalid_request_error", HTTPStatus.BAD_REQUEST)
                return

            client_ip = resolve_client_ip(self.headers, getattr(self, "client_address", None))
            user_agent = self.headers.get("User-Agent", "")

            success = send_contact_inquiry(
                from_name=name,
                from_email=email,
                topic=topic,
                message=message,
                ip_address=client_ip,
                user_agent=user_agent,
            )

            if success:
                self._send_json({"status": "ok", "message": "Inquiry sent successfully"})
            else:
                self._send_error_response(
                    "Failed to send message. Please contact mesh@inetconnector.com directly.",
                    "internal_error",
                    HTTPStatus.INTERNAL_SERVER_ERROR,
                )
            return

        if clean_path in ("/v1/billing/topup", "/api/v1/billing/topup", "/api/billing/topup", "/billing/topup"):
            res, err, status = self.billing_routes.handle_post_topup(self.headers, body)
            if err:
                self._send_error_response(err, "billing_error", status)
            else:
                self._send_json(res or {}, status)
            return

        if clean_path in ("/v1/billing/checkout", "/api/v1/billing/checkout", "/api/billing/checkout", "/billing/checkout"):
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

        if clean_path in (
            "/models/load",
            "/webui/models/load",
            "/models/unload",
            "/webui/models/unload",
            "/v1/models/load",
            "/v1/models/unload",
        ):
            self._send_json({"status": "ok", "message": "model ready"})
            return

        if clean_path in (
            "/v1/chat/completions",
            "/chat/completions",
            "/completion",
            "/completions",
            "/v1/completions",
            "/webui/chat/completions",
            "/webui/completion",
            "/webui/completions",
            "/webui/v1/chat/completions",
            "/webui/v1/completions",
            "/infill",
            "/webui/infill",
        ):
            self._handle_chat_completions(body)
            return

        if clean_path in ("/tokenize", "/webui/tokenize", "/api/tokenize"):
            content = str(body.get("content", ""))
            tokens = [ord(c) for c in content]
            self._send_json({"tokens": tokens})
            return

        if clean_path in ("/detokenize", "/webui/detokenize", "/api/detokenize"):
            tokens = body.get("tokens", [])
            content = "".join(chr(t) for t in tokens if isinstance(t, int) and 0 <= t < 0x110000)
            self._send_json({"content": content})
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

    def _handle_props(self) -> None:
        models = current_models()
        default_model = models[0].id if models else "qwen2.5:7b"
        props = {
            "default_generation_settings": {
                "n_ctx": 32768,
                "n_predict": -1,
                "model": default_model,
                "params": {
                    "temperature": 0.7,
                    "top_k": 40,
                    "top_p": 0.95,
                    "min_p": 0.05,
                    "n_predict": -1,
                    "n_keep": 0,
                    "stop": ["<|im_end|>", "<|endoftext|>"],
                    "samplers": ["top_k", "top_p", "min_p", "temperature"],
                },
            },
            "total_slots": 1,
            "chat_template": "{% for message in messages %}{{'<|im_start|>' + message['role'] + '\\n' + message['content'] + '<|im_end|>\\n'}}{% endfor %}{% if add_generation_prompt %}{{'<|im_start|>assistant\\n'}}{% endif %}",
            "modalities": ["text", "vision"],
            "webui_settings": {
                "theme": "Dark",
                "system_message": "Du bist ComputeMesh AI, ein hochperformanter intelligenter Assistent im dezentralen GPU-Netzwerk mit Live-Werkzeugen.",
            },
            "role": "model",
            "build": f"computemesh-gateway-{CONFIG.appliance_version}",
            "commit": "master",
        }
        self._send_json(props)

    def _handle_slots(self) -> None:
        models = current_models()
        default_model = models[0].id if models else "qwen2.5:7b"
        slots = [
            {
                "id": 0,
                "state": 0,
                "model": default_model,
                "n_ctx": 32768,
                "params": {},
            }
        ]
        self._send_json(slots)

    def _handle_models(self) -> None:
        models = current_models()
        if not models and os.environ.get("COMPUTEMESH_MODEL_REGISTRY_URL", "").strip():
            self._send_error_response("Model registry unavailable", "service_unavailable", HTTPStatus.SERVICE_UNAVAILABLE)
            return
        models_data = [
            {
                "id": m.id,
                "object": "model",
                "created": getattr(m, "created", 0),
                "owned_by": getattr(m, "owned_by", "computemesh"),
                "permission": [],
                "root": m.id,
                "parent": None,
            }
            for m in models
        ]
        self._send_json({"object": "list", "data": models_data})

    def _handle_ollama_tags(self) -> None:
        models = current_models()
        if not models and os.environ.get("COMPUTEMESH_MODEL_REGISTRY_URL", "").strip():
            self._send_error_response("Model registry unavailable", "service_unavailable", HTTPStatus.SERVICE_UNAVAILABLE)
            return
        models_data = [
            {
                "name": m.id,
                "model": m.id,
                "modified_at": datetime.now(timezone.utc).isoformat(),
                "size": getattr(m, "artifact_size_bytes", 0) or (4350000000 if "7b" in m.id or "8b" in m.id else 41000000000),
                "digest": getattr(m, "artifact_digest", "") or f"sha256:{secrets.token_hex(32)}",
                "details": {
                    "parent_model": "",
                    "format": "computemesh-gateway",
                    "family": "qwen2_vl" if "vl" in m.id else ("llama" if "llama" in m.id else ("qwen2" if "qwen" in m.id else ("llava" if "llava" in m.id else "deepseek"))),
                    "families": ["qwen2_vl", "clip"] if "vl" in m.id else (["llama", "clip"] if "vision" in m.id else (["llava", "clip"] if "llava" in m.id else ["llama" if "llama" in m.id else ("qwen2" if "qwen" in m.id else "deepseek")])),
                    "parameter_size": "7.6B" if "7b" in m.id or "8b" in m.id else ("11.0B" if "11b" in m.id else "70.6B"),
                    "quantization_level": getattr(m, "quantization", "") or "Q4_K_M",
                    "availability": getattr(m, "availability", "available_warm"),
                },
            }
            for m in models
        ]
        self._send_json({"models": models_data})

    def _handle_ollama_show(self, body: dict[str, Any]) -> None:
        requested = str(body.get("name", "") or body.get("model", "")).strip()
        model_id = resolve_model_id(requested)
        is_vision = "vl" in model_id.lower() or "vision" in model_id.lower() or "llava" in model_id.lower()
        family = "qwen2_vl" if "vl" in model_id.lower() else ("llama" if "llama" in model_id.lower() else ("llava" if "llava" in model_id.lower() else "qwen2"))
        self._send_json({
            "modelfile": f"# ComputeMesh Dynamic Modelfile\nFROM {model_id}\nTEMPLATE \"\"\"{{{{ .Prompt }}}}\"\"\"",
            "parameters": f"stop                           \"<|im_end|>\"\ncontext_length                 32768",
            "template": "{{ .Prompt }}",
            "details": {
                "parent_model": "",
                "format": "gguf",
                "family": family,
                "families": [family, "clip"] if is_vision else [family],
                "parameter_size": "7.6B" if "7b" in model_id else ("11.0B" if "11b" in model_id else "70.6B"),
                "quantization_level": "Q4_K_M",
            },
            "model_info": {
                "general.architecture": family,
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
        if not messages and "prompt" in body:
            prompt_val = body.get("prompt")
            if isinstance(prompt_val, str) and prompt_val:
                messages = [{"role": "user", "content": prompt_val}]
            elif isinstance(prompt_val, list):
                messages = [{"role": "user", "content": " ".join(str(p) for p in prompt_val)}]
        stream = bool(body.get("stream", False))
        if "enable_mcp" in body:
            enable_mcp = bool(body.get("enable_mcp"))
        elif "tools" in body:
            tools_val = body.get("tools")
            enable_mcp = bool(tools_val) if isinstance(tools_val, list) else True
        else:
            enable_mcp = True
        max_tokens_val = body.get("max_tokens") or body.get("max_completion_tokens")
        max_tokens = int(max_tokens_val) if max_tokens_val is not None and str(max_tokens_val).isdigit() else None
        client_ip = resolve_client_ip(self.headers, getattr(self, "client_address", None))

        is_node_tunnel = getattr(self, "_is_node_tunnel", False)
        is_teaser = auth.is_teaser and not is_node_tunnel
        is_self_compute = auth.is_provider_self_compute or is_node_tunnel

        if auth.is_quota_exceeded and not is_node_tunnel:
            self._send_teaser_quota_response(client_ip)
            return

        if not stream:
            res, err, status = self.inference_engine.execute_chat_completion(
                account_id=auth.account_id or "cust_default",
                model_id=model_id,
                messages=messages,
                is_teaser=is_teaser,
                is_provider_self_compute=is_self_compute,
                client_ip=client_ip,
                max_tokens=max_tokens,
                enable_mcp=enable_mcp,
            )
            if err:
                self._send_error_response(err, "inference_error", status)
            else:
                headers = self.teaser_manager.response_headers(client_ip) if is_teaser else None
                self._send_json(res or {}, HTTPStatus(status), headers)
            return

        # SSE Streaming response
        try:
            stream_gen = self.inference_engine.stream_chat_completions(
                account_id=auth.account_id or "cust_default",
                model_id=model_id,
                messages=messages,
                is_teaser=is_teaser,
                is_provider_self_compute=is_self_compute,
                client_ip=client_ip,
                max_tokens=max_tokens,
                enable_mcp=enable_mcp,
            )
            first_chunk = next(stream_gen, None)
        except InsufficientBalanceError as exc:
            self._send_error_response(str(exc), "insufficient_quota", HTTPStatus.PAYMENT_REQUIRED)
            return
        except InferenceBackendError as exc:
            self._send_error_response(sanitize_error_message(exc), "inference_error", HTTPStatus.SERVICE_UNAVAILABLE)
            return
        except Exception as exc:
            self._send_error_response(sanitize_error_message(exc), "internal_error", HTTPStatus.INTERNAL_SERVER_ERROR)
            return

        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", "text/event-stream; charset=utf-8")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Connection", "close")
        for h_name, h_val in SECURITY_HEADERS.items():
            self.send_header(h_name, h_val)
        self.end_headers()
        if first_chunk:
            self.wfile.write(first_chunk)
            self.wfile.flush()
        for chunk in stream_gen:
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
        images = body.get("images") if isinstance(body.get("images"), list) else None
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
                images=images,
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
            images=images,
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
