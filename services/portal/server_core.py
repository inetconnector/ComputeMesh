"""ComputeMesh Public Web Portal & Customer Billing Gateway Server.

Serves the official bilingual public portal (mesh.inetconnector.com)
with clean URL routing for docs, status, benchmarks, legal pages, registration, and quotes.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hmac
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import re
import sys
from typing import Any
import urllib.parse

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from config import CONFIG
from services.gateway.auth import resolve_client_ip
from services.gateway.dashboard import (
    NODE_TELEMETRY_REGISTRY,
    fresh_node_telemetry_entries,
    render_node_remote_dashboard_html,
    save_node_telemetry_registry,
)
from services.gateway.security import (
    GLOBAL_RATE_LIMITER,
    SECURITY_HEADERS,
    sanitize_error_message,
)
from services.portal.routes_quotes import PortalQuotesHandler
from services.portal.routes_registration import REGISTERED_ACCOUNTS, PortalRegistrationHandler
from services.portal.passkey_routes import PasskeyAuthHandler, session_account_from_headers
from services.portal.routes_downloads import get_download_file_response
from services.portal.routes_payouts import PortalPayoutsHandler
from services.portal.mail_dispatcher import send_contact_inquiry
from services.billing.stripe_connect import is_stripe_connect_platform_activation_error

PORTAL_DIR = (REPO_ROOT / "portal").resolve()
NODE_ID_REGEX = re.compile(r"^[a-zA-Z0-9_\-\.]{3,64}$")
NODE_AUTH_TOKEN_REGEX = re.compile(r"^cm_tunnel_[a-fA-F0-9]{32,128}$")

ROUTE_MAP: dict[str, str] = {
    "/": "index.html",
    "/docs": "docs.html",
    "/status": "status.html",
    "/benchmarks": "benchmarks.html",
    "/terms": "terms.html",
    "/privacy": "privacy.html",
    "/impressum": "impressum.html",
    "/contact": "contact.html",
    "/fleet": "fleet.html",
    "/billing/cancel": "billing/cancel.html",
    "/billing/success": "billing/success.html",
    "/google55d49cbebf6659d4.html": "google55d49cbebf6659d4.html",
}

STATIC_TEXT_ROUTES: dict[str, tuple[str, str]] = {
    "/robots.txt": ("robots.txt", "text/plain"),
    "/sitemap.xml": ("sitemap.xml", "application/xml"),
}


def _safe_resolve_portal_file(filename: str) -> Path | None:
    """Canonicalizes and verifies that a target file strictly resides within PORTAL_DIR."""
    if "\0" in filename or ".." in filename:
        return None
    try:
        candidate = (PORTAL_DIR / filename.lstrip("/")).resolve()
        if candidate.is_relative_to(PORTAL_DIR) and candidate.is_file():
            return candidate
    except Exception:
        return None
    return None


class PortalHandler(BaseHTTPRequestHandler):
    """High-performance Hardened HTTP Request Handler for Public Web Portal."""

    server_version = "ComputeMesh-Portal/1.2"
    sys_version = ""

    registration_handler: PortalRegistrationHandler = PortalRegistrationHandler()
    quotes_handler: PortalQuotesHandler = PortalQuotesHandler()
    passkey_handler: PasskeyAuthHandler = PasskeyAuthHandler()
    payouts_handler: PortalPayoutsHandler = PortalPayoutsHandler()

    def log_message(self, format: str, *args: Any) -> None:
        pass

    def _check_rate_limit(self) -> bool:
        client_ip = resolve_client_ip(self.headers, getattr(self, "client_address", None))
        allowed, retry_after = GLOBAL_RATE_LIMITER.is_allowed(f"portal_ip_{client_ip}", is_authenticated=False)
        if not allowed:
            self.send_response(HTTPStatus.TOO_MANY_REQUESTS)
            self.send_header("Content-Type", "text/plain")
            for h_name, h_val in SECURITY_HEADERS.items():
                self.send_header(h_name, h_val)
            self.send_header("Retry-After", str(retry_after))
            self.send_header("Content-Length", "19")
            self.send_header("Connection", "close")
            self.end_headers()
            self.wfile.write(b"Rate limit exceeded")
            self.close_connection = True
            return False
        return True

    def _send_file(self, path: Path, content_type: str, status: HTTPStatus = HTTPStatus.OK) -> None:
        data = path.read_bytes()
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        for h_name, h_val in SECURITY_HEADERS.items():
            self.send_header(h_name, h_val)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Connection", "close")
        self.end_headers()
        self.wfile.write(data)
        self.close_connection = True

    def _send_bytes(self, data: bytes, content_type: str, status: int = HTTPStatus.OK) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        for h_name, h_val in SECURITY_HEADERS.items():
            self.send_header(h_name, h_val)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Connection", "close")
        self.end_headers()
        self.wfile.write(data)
        self.close_connection = True

    def _send_json(
        self,
        data: dict[str, Any],
        status: HTTPStatus = HTTPStatus.OK,
        set_cookie: str | None = None,
        credentialed: bool = False,
    ) -> None:
        body = json.dumps(data, indent=2).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        for h_name, h_val in SECURITY_HEADERS.items():
            self.send_header(h_name, h_val)
        # Session-authenticated JSON routes (auth/*, portal/*) carry credentials via
        # cookie, so a wildcard CORS origin would let any third-party site read them
        # cross-site; only the portal's own origin may fetch() those with credentials.
        if credentialed or set_cookie is not None:
            self.send_header("Access-Control-Allow-Origin", f"{CONFIG.endpoints.scheme}://{CONFIG.endpoints.domain}")
            self.send_header("Access-Control-Allow-Credentials", "true")
        else:
            self.send_header("Access-Control-Allow-Origin", "*")
        if set_cookie is not None:
            self.send_header("Set-Cookie", set_cookie)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Connection", "close")
        self.end_headers()
        self.wfile.write(body)
        self.close_connection = True

    def _authorize_node_view(self, node_id: str, supplied_token: str) -> tuple[dict[str, Any] | None, HTTPStatus | None]:
        if not NODE_ID_REGEX.match(node_id):
            return (None, HTTPStatus.BAD_REQUEST)
        node_data = NODE_TELEMETRY_REGISTRY.get(node_id)
        if not node_data:
            return (None, HTTPStatus.NOT_FOUND)
        expected = str(node_data.get("auth_token", "")).strip()
        if not expected or not supplied_token or not hmac.compare_digest(supplied_token, expected):
            return (None, HTTPStatus.UNAUTHORIZED)
        return (node_data, None)

    def do_OPTIONS(self) -> None:
        self.send_response(HTTPStatus.OK)
        for h_name, h_val in SECURITY_HEADERS.items():
            self.send_header(h_name, h_val)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, Authorization, X-Node-Auth-Token")
        self.send_header("Connection", "close")
        self.end_headers()
        self.close_connection = True

    def do_GET(self) -> None:
        if not self._check_rate_limit():
            return

        clean_path = self.path.split("?")[0].rstrip("/")
        query = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)

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

        parsed_url = urllib.parse.urlparse(self.path)
        clean_path = parsed_url.path.rstrip("/")
        if clean_path == "":
            clean_path = "/"

        query_params = urllib.parse.parse_qs(parsed_url.query)

        # Dynamic 1-Click Launch & Reset Script Downloads for Fleet Operators
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
                    query_params.get("key", [""])[0].strip()
                    or query_params.get("owner_key", [""])[0].strip()
                    or self.headers.get("X-Owner-Key", "").strip()
                )
                if not owner_key:
                    auth_hdr = self.headers.get("Authorization", "").strip()
                    if auth_hdr.startswith("Bearer "):
                        candidate = auth_hdr[7:].strip()
                        if candidate.startswith("inet-") or candidate.startswith("ok_") or candidate.startswith("owner_") or candidate.startswith("cm_owner_") or candidate.startswith("owk_"):
                            owner_key = candidate

            os_target = query_params.get("os", ["windows"])[0].strip()
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

        # Authenticated Node Remote Dashboard Viewer
        if clean_path.startswith("/node/"):
            node_id = clean_path.removeprefix("/node/").strip()
            auth_token = query_params.get("auth", [""])[0].strip()
            node_data, auth_status = self._authorize_node_view(node_id, auth_token)
            if auth_status is not None:
                self._send_json({"error": "Node dashboard unavailable or unauthorized"}, auth_status)
                return
            html = render_node_remote_dashboard_html(node_id, auth_token, node_data)
            self._send_bytes(html.encode("utf-8"), "text/html; charset=utf-8")
            return

        # Authenticated Node Status API for remote dashboard live polling
        if clean_path.startswith("/api/v1/node/") and clean_path.endswith("/status"):
            parts = clean_path.split("/")
            if len(parts) >= 5:
                node_id = parts[4]
                auth_token = query_params.get("auth", [""])[0].strip()
                if not auth_token:
                    auth_token = self.headers.get("X-Node-Auth-Token", "").strip()
                node_data, auth_status = self._authorize_node_view(node_id, auth_token)
                if auth_status is not None:
                    self._send_json({"error": "Node status unavailable or unauthorized"}, auth_status)
                    return
                self._send_json(node_data)
                return

        if clean_path in ROUTE_MAP:
            target_file = _safe_resolve_portal_file(ROUTE_MAP[clean_path])
            if target_file and target_file.exists():
                self._send_bytes(target_file.read_bytes(), "text/html; charset=utf-8")
                return

        if clean_path in STATIC_TEXT_ROUTES:
            filename, content_type = STATIC_TEXT_ROUTES[clean_path]
            target_file = _safe_resolve_portal_file(filename)
            if target_file and target_file.exists():
                self._send_bytes(target_file.read_bytes(), content_type)
                return

        if clean_path == "/portal.css":
            css_file = _safe_resolve_portal_file("portal.css")
            if css_file and css_file.exists():
                self._send_bytes(css_file.read_bytes(), "text/css; charset=utf-8")
                return

        if clean_path == "/portal.js":
            js_file = _safe_resolve_portal_file("portal.js")
            if js_file and js_file.exists():
                self._send_bytes(js_file.read_bytes(), "application/javascript; charset=utf-8")
                return

        if clean_path == "/api/v1/mesh/stats":
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

        if clean_path == "/api/auth/me":
            account = session_account_from_headers(self.headers)
            if account is None:
                self._send_json({"error": "not signed in"}, HTTPStatus.UNAUTHORIZED, credentialed=True)
                return
            self._send_json(
                {"account_id": account.account_id, "email": account.email, "owner_key": account.owner_key},
                credentialed=True,
            )
            return

        if clean_path == "/api/auth/passkeys":
            data, status, cookie = self.passkey_handler.list_passkeys(self.headers)
            self._send_json(data, status, set_cookie=cookie, credentialed=True)
            return

        if clean_path == "/api/portal/fleet/audit_log":
            data, status, cookie = self.passkey_handler.get_audit_log(self.headers)
            self._send_json(data, status, set_cookie=cookie, credentialed=True)
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
                self._send_json({"error": "not signed in"}, HTTPStatus.UNAUTHORIZED, credentialed=True)
                return

            from services.gateway.server import _build_fleet_payload, owner_id_for_key
            owner_id = owner_id_for_key(owner_key)
            self._send_json(_build_fleet_payload(owner_id, include_remote_urls=True), credentialed=True)
            return

        if clean_path in ("/api/v1/mesh/fleet", "/mesh/fleet"):
            from services.gateway.server import _build_fleet_payload, owner_id_for_key

            owner_key = query_params.get("owner_key", [""])[0].strip() or self.headers.get("X-Owner-Key", "").strip()
            owner_id = owner_id_for_key(owner_key)
            if not owner_id:
                self._send_json({"error": "owner_key query parameter is required"}, HTTPStatus.BAD_REQUEST)
                return

            self._send_json(_build_fleet_payload(owner_id, include_remote_urls=True))
            return

        if clean_path == "/api/portal/fleet/payouts":
            account = session_account_from_headers(self.headers)
            owner_key = ""
            if account is not None:
                owner_key = account.owner_key
            else:
                owner_key = query_params.get("owner_key", [""])[0].strip() or self.headers.get("X-Owner-Key", "").strip()
                if not owner_key:
                    auth_hdr = self.headers.get("Authorization", "").strip()
                    if auth_hdr.startswith("Bearer "):
                        candidate = auth_hdr[7:].strip()
                        if candidate.startswith("inet-") or candidate.startswith("ok_") or candidate.startswith("owner_") or candidate.startswith("cm_owner_") or candidate.startswith("owk_"):
                            owner_key = candidate
            if not owner_key and account is None:
                self._send_json({"error": "not signed in"}, HTTPStatus.UNAUTHORIZED, credentialed=True)
                return
            from services.gateway.server import owner_id_for_key
            owner_id = owner_id_for_key(owner_key)
            if not owner_id:
                self._send_json({"error": "invalid owner key"}, HTTPStatus.UNAUTHORIZED, credentialed=True)
                return
            data = self.payouts_handler.get_payout_overview(owner_id)
            self._send_json(data, credentialed=True)
            return

        if clean_path.startswith("/downloads/"):
            dl_name = clean_path.removeprefix("/downloads/")
            body = f"ComputeMesh Binary Package: {dl_name}\nBuild: v1.0-release\n".encode("utf-8")
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Disposition", f'attachment; filename="{dl_name}"')
            self.send_header("Content-Type", "application/octet-stream")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Connection", "close")
            self.end_headers()
            self.wfile.write(body)
            self.close_connection = True
            return

        self.send_error(HTTPStatus.NOT_FOUND, "Resource Not Found")

    def do_POST(self) -> None:
        if not self._check_rate_limit():
            return

        clean_path = self.path.split("?")[0].rstrip("/")
        length = int(self.headers.get("Content-Length", 0))
        if length > 10 * 1024 * 1024:
            self._send_json({"error": "Payload too large"}, HTTPStatus.REQUEST_ENTITY_TOO_LARGE)
            return

        raw_data = self.rfile.read(length) if length > 0 else b"{}"

        try:
            body = json.loads(raw_data.decode("utf-8"))
        except Exception:
            body = {}

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
                self._send_json({"error": "not signed in"}, HTTPStatus.UNAUTHORIZED, credentialed=True)
                return
            from services.gateway.server import owner_id_for_key
            owner_id = owner_id_for_key(owner_key)
            if not owner_id:
                self._send_json({"error": "invalid owner key"}, HTTPStatus.UNAUTHORIZED, credentialed=True)
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
                    self._send_json(data, credentialed=True)
                except Exception as exc:
                    status = HTTPStatus.SERVICE_UNAVAILABLE if is_stripe_connect_platform_activation_error(exc) else HTTPStatus.BAD_REQUEST
                    self._send_json({"error": str(exc)}, status, credentialed=True)
                return

            if clean_path == "/api/portal/fleet/payouts/refresh":
                data = self.payouts_handler.refresh_status(owner_id)
                self._send_json(data, credentialed=True)
                return

            if clean_path == "/api/portal/fleet/payouts/settle":
                amount_micro = body.get("amount_micro_units")
                try:
                    data = self.payouts_handler.execute_settlement(owner_id, amount_micro)
                    if "error" in data:
                        self._send_json(data, HTTPStatus.BAD_REQUEST, credentialed=True)
                    else:
                        self._send_json(data, credentialed=True)
                except Exception as exc:
                    self._send_json({"error": str(exc)}, HTTPStatus.BAD_REQUEST, credentialed=True)
                return

        if clean_path == "/api/v1/node/heartbeat":
            node_id = str(body.get("node_id", "")).strip()
            auth_token = str(body.get("auth_token", "")).strip()
            if not node_id or not NODE_ID_REGEX.match(node_id):
                self._send_json({"error": "Valid node_id is required"}, HTTPStatus.BAD_REQUEST)
                return
            if not NODE_AUTH_TOKEN_REGEX.match(auth_token):
                self._send_json({"error": "Valid node auth token is required"}, HTTPStatus.UNAUTHORIZED)
                return

            existing_node = NODE_TELEMETRY_REGISTRY.get(node_id)
            if existing_node:
                expected_token = str(existing_node.get("auth_token", "")).strip()
                if expected_token and not hmac.compare_digest(auth_token, expected_token):
                    self._send_json({"error": "Unauthorized node heartbeat: token mismatch"}, HTTPStatus.UNAUTHORIZED)
                    return

            sent_owner_key = str(body.get("owner_key", "")).strip()
            resolved_owner_key = FLEET_ACCOUNT_STORE.resolve_latest_owner_key(sent_owner_key) if sent_owner_key else ""
            active_owner_key = resolved_owner_key or sent_owner_key
            key_rotated = bool(resolved_owner_key and resolved_owner_key != sent_owner_key)

            from services.gateway.server import OWNER_ACCOUNT_STORE, owner_id_for_key, OwnerAccountStoreError
            owner_id = owner_id_for_key(active_owner_key)
            if owner_id:
                if not OWNER_ACCOUNT_STORE.is_node_unbound(owner_id, node_id):
                    try:
                        OWNER_ACCOUNT_STORE.ensure_owner(owner_id)
                        OWNER_ACCOUNT_STORE.bind_provider_node(owner_id, node_id)
                    except OwnerAccountStoreError:
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
            # Deliberately do not set updated_at=now_iso for relayed peers so they do not falsely appear as direct online nodes
            gm = body.get("global_mesh", {})
            for peer in gm.get("nodes", []):
                p_id = str(peer.get("node_id", "")).strip()
                if p_id and p_id != node_id and p_id not in ("windows-laptop", "unnamed-node"):
                    p_vram_gb = float(peer.get("vram_gb", 0.0))
                    p_vram_bytes = int(p_vram_gb * 1024 * 1024 * 1024)
                    p_tflops = float(peer.get("tflops", 0.0))
                    p_gpus_cnt = int(peer.get("gpus_count", 1))

                    if p_id not in NODE_TELEMETRY_REGISTRY:
                        NODE_TELEMETRY_REGISTRY[p_id] = {
                            "node_id": p_id,
                            "auth_token": f"peer_relayed_{p_id}",
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
            self._send_json({
                "status": "ok",
                "message": "heartbeat registered",
                "node_id": node_id,
                "owner_key": active_owner_key,
                "key_rotated": key_rotated,
            }, HTTPStatus.OK)
            return

        if clean_path in ("/api/v1/node/sync_key", "/api/node/sync_key"):
            node_id = str(body.get("node_id", "")).strip()
            auth_token = str(body.get("auth_token", "")).strip()
            sent_owner_key = str(body.get("owner_key", "")).strip()
            if not node_id:
                self._send_json({"error": "Valid node_id is required"}, HTTPStatus.BAD_REQUEST)
                return
            if not auth_token:
                self._send_json({"error": "auth_token is required"}, HTTPStatus.UNAUTHORIZED)
                return

            resolved = FLEET_ACCOUNT_STORE.resolve_latest_owner_key(sent_owner_key) if sent_owner_key else ""
            active_key = resolved or sent_owner_key
            key_rotated = bool(resolved and resolved != sent_owner_key)
            self._send_json({
                "status": "ok",
                "node_id": node_id,
                "owner_key": active_key,
                "key_rotated": key_rotated,
            }, HTTPStatus.OK)
            return

        if clean_path in ("/api/portal/fleet/unbind_node", "/api/v1/mesh/fleet/unbind_node"):
            from services.gateway.server import OWNER_ACCOUNT_STORE, owner_id_for_key
            node_id = str(body.get("node_id", "")).strip()
            if not node_id:
                self._send_json({"error": "node_id is required"}, HTTPStatus.BAD_REQUEST)
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

            self._send_json({"status": "ok", "unbound": unbound, "node_id": node_id}, HTTPStatus.OK)
            return

        if clean_path == "/api/auth/register/begin":
            data, status, cookie = self.passkey_handler.register_begin(body, self.headers, self.client_address)
            self._send_json(data, status, set_cookie=cookie, credentialed=True)
            return

        if clean_path == "/api/auth/register/complete":
            data, status, cookie = self.passkey_handler.register_complete(body, self.headers, self.client_address)
            self._send_json(data, status, set_cookie=cookie, credentialed=True)
            return

        if clean_path == "/api/auth/login/begin":
            data, status, cookie = self.passkey_handler.login_begin(body, self.headers, self.client_address)
            self._send_json(data, status, set_cookie=cookie, credentialed=True)
            return

        if clean_path == "/api/auth/login/complete":
            data, status, cookie = self.passkey_handler.login_complete(body, self.headers, self.client_address)
            self._send_json(data, status, set_cookie=cookie, credentialed=True)
            return

        if clean_path == "/api/auth/magic_link/request":
            data, status, cookie = self.passkey_handler.request_magic_link(body, self.headers, self.client_address)
            self._send_json(data, status, set_cookie=cookie, credentialed=True)
            return

        if clean_path == "/api/auth/magic_link/verify":
            data, status, cookie = self.passkey_handler.verify_magic_link(body, self.headers, self.client_address)
            self._send_json(data, status, set_cookie=cookie, credentialed=True)
            return

        if clean_path == "/api/auth/passkeys/delete":
            data, status, cookie = self.passkey_handler.delete_passkey(self.headers, body, self.client_address)
            self._send_json(data, status, set_cookie=cookie, credentialed=True)
            return

        if clean_path == "/api/auth/passkeys/rename":
            data, status, cookie = self.passkey_handler.rename_passkey(self.headers, body)
            self._send_json(data, status, set_cookie=cookie, credentialed=True)
            return

        if clean_path == "/api/portal/fleet/enrollment_token":
            data, status, cookie = self.passkey_handler.create_enrollment_token(self.headers)
            self._send_json(data, status, set_cookie=cookie, credentialed=True)
            return

        if clean_path in ("/api/auth/owner_key/rotate", "/api/portal/owner_key/rotate"):
            data, status, cookie = self.passkey_handler.rotate_owner_key(self.headers, body, self.client_address)
            self._send_json(data, status, set_cookie=cookie, credentialed=True)
            return

        if clean_path == "/api/auth/logout":
            data, status, cookie = self.passkey_handler.logout(self.headers)
            self._send_json(data, status, set_cookie=cookie, credentialed=True)
            return

        if clean_path == "/api/v1/register":
            res, err, status = self.registration_handler.handle_register(body)
            if err:
                self._send_json({"error": err}, status)
            else:
                self._send_json(res or {}, status)
            return

        if clean_path == "/api/v1/billing/quote":
            res, err, status = self.quotes_handler.handle_quote(body)
            if err:
                self._send_json({"error": err}, status)
            else:
                self._send_json(res or {}, status)
            return

        if clean_path in ("/api/v1/contact", "/api/contact"):
            name = str(body.get("name", "")).strip()
            email = str(body.get("email", "")).strip()
            topic = str(body.get("topic", "developer")).strip()
            message = str(body.get("message", "")).strip()

            if not name or len(name) < 2:
                self._send_json({"error": "Name is required (min 2 characters)"}, HTTPStatus.BAD_REQUEST)
                return
            if not email or "@" not in email or "." not in email:
                self._send_json({"error": "Valid email address is required"}, HTTPStatus.BAD_REQUEST)
                return
            if not message or len(message) < 3:
                self._send_json({"error": "Message is required (min 3 characters)"}, HTTPStatus.BAD_REQUEST)
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
                self._send_json({"status": "ok", "message": "Inquiry sent successfully"}, HTTPStatus.OK)
            else:
                self._send_json(
                    {"error": "Failed to send message. Please contact mesh@inetconnector.com directly."},
                    HTTPStatus.INTERNAL_SERVER_ERROR,
                )
            return

        self.send_error(HTTPStatus.NOT_FOUND, "Not Found")


def run_portal_server(host: str = "0.0.0.0", port: int = 3000) -> None:
    server = ThreadingHTTPServer((host, port), PortalHandler)
    print(f"ComputeMesh Public Portal Server running at http://{host}:{port}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nShutting down portal server...")
    finally:
        server.server_close()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="ComputeMesh Public Web Portal Server")
    parser.add_argument("--host", default="0.0.0.0", help="Bind address (default: 0.0.0.0)")
    parser.add_argument("--port", type=int, default=3000, help="Listen port (default: 3000)")
    args = parser.parse_args(argv)

    run_portal_server(host=args.host, port=args.port)
    return 0


if __name__ == "__main__":
    sys.exit(main())
