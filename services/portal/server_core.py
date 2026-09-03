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

    def _send_json(self, data: dict[str, Any], status: HTTPStatus = HTTPStatus.OK) -> None:
        body = json.dumps(data, indent=2).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        for h_name, h_val in SECURITY_HEADERS.items():
            self.send_header(h_name, h_val)
        self.send_header("Access-Control-Allow-Origin", "*")
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

        if clean_path in ("/api/v1/mesh/fleet", "/mesh/fleet"):
            from services.gateway.server import OWNER_ACCOUNT_STORE, owner_id_for_key
            from tools.appliance.hardware_detector import is_integrated_display_adapter

            owner_key = query_params.get("owner_key", [""])[0].strip()
            owner_id = owner_id_for_key(owner_key)
            if not owner_id:
                self._send_json({"error": "owner_key query parameter is required"}, HTTPStatus.BAD_REQUEST)
                return

            bound_node_ids = set(OWNER_ACCOUNT_STORE.list_provider_nodes(owner_id))
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
                nodes_out.append({
                    "node_id": n.get("node_id"),
                    "vram_gb": round(node_vram / (1024**3), 1),
                    "tflops": round(node_tflops, 1),
                    "gpus": [g.get("model_name") for g in gpus],
                    "updated_at": n.get("updated_at"),
                })

            self._send_json({
                "owner_id": owner_id,
                "total_nodes_bound": len(bound_node_ids),
                "total_nodes_online": len(fleet_nodes),
                "total_vram_gb": round(total_vram_bytes / (1024**3), 1),
                "total_tflops": round(total_tflops, 1),
                "nodes": nodes_out,
                "timestamp": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            })
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

            now_iso = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
            NODE_TELEMETRY_REGISTRY[node_id] = {
                "node_id": node_id,
                "auth_token": auth_token,
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
                            "updated_at": now_iso,
                        }

            save_node_telemetry_registry(NODE_TELEMETRY_REGISTRY)
            self._send_json({"status": "ok", "message": "heartbeat registered", "node_id": node_id}, HTTPStatus.OK)
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
