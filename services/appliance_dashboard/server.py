"""ComputeMesh Embedded Appliance Web Dashboard Server.

Clean, modular HTTP server delegating to specialized routers and sub-handlers.
"""
from __future__ import annotations

import argparse
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import ipaddress
import hmac
import json
import logging
from pathlib import Path
import secrets
import sys
from typing import Any
import urllib.parse

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from config import CONFIG
from tools.appliance.appliance_config import (
    ApplianceConfig,
    load_appliance_config,
)
from tools.appliance.hardware_detector import (
    RigInventory,
    scan_rig_hardware_stable,
)
from services.appliance_dashboard.template_loader import get_dashboard_html
from services.appliance_dashboard.mesh_aggregator import (
    MeshRegistryAggregator,
    GLOBAL_MESH_AGGREGATOR,
)
from services.appliance_dashboard.tunnel_relay import (
    get_or_create_node_auth_token,
    NODE_AUTH_TOKEN,
    CloudTunnelRelay,
    CLOUD_TUNNEL_RELAY,
)
from services.appliance_dashboard.inference_router import InferenceRouter
from services.appliance_dashboard.fan_control_handler import FanControlHandler
from services.appliance_dashboard.model_manager_handler import ModelManagerHandler
from services.appliance_dashboard.system_actions import SystemActionsHandler
from services.appliance_dashboard.killswitch_actions import KillswitchHandler
from services.appliance_dashboard.telemetry_handler import TelemetryHandler
from services.appliance_dashboard.webapp_handler import WebAppsHandler

log = logging.getLogger("computemesh.appliance.server")
APPLIANCE_VERSION = CONFIG.appliance_version
PORTAL_DIR = (REPO_ROOT / "portal").resolve()
DASHBOARD_SESSION_COOKIE = "cm_dashboard_session"
# Kept for explicit legacy/operator sessions supplied in a header or cookie.
# The dashboard never mints this process-wide value for anonymous visitors.
DASHBOARD_SESSION_TOKEN = secrets.token_urlsafe(32)
MAX_REQUEST_BODY_BYTES = 10 * 1024 * 1024
ALLOWED_CORS_ORIGINS = {
    "https://mesh.inetconnector.com",
    "https://ai.inetconnector.com",
    "https://inetconnector.com",
    "http://localhost:3000",
    "http://127.0.0.1:3000",
}
FAN_SAFETY_CONTROLLER: Any = None


def _safe_resolve_portal_file(filename: str) -> Path | None:
    """Canonicalizes and verifies that a target file strictly resides within PORTAL_DIR or PyInstaller MEIPASS."""
    if "\0" in filename or ".." in filename:
        return None
    sub_path = filename.lstrip("/\\")
    candidates: list[Path] = []
    if hasattr(sys, "_MEIPASS"):
        candidates.append(Path(sys._MEIPASS) / "portal" / sub_path)
        candidates.append(Path(sys._MEIPASS) / sub_path)
    candidates.append(PORTAL_DIR / sub_path)
    candidates.append(REPO_ROOT / "portal" / sub_path)

    for c in candidates:
        try:
            resolved = c.resolve()
            if resolved.is_file():
                return resolved
        except Exception:
            continue
    return None




class DashboardHandler(BaseHTTPRequestHandler):
    """Slim coordinator HTTP request handler delegating to modular sub-handlers."""
    server_version = "ComputeMesh-NodeOS/1.2"
    sys_version = ""

    config: ApplianceConfig
    inventory: RigInventory
    node_id: str
    tokens_served: int = 0
    earnings_cm: float = 0.0

    def _current_node_id(self) -> str:
        configured = str(getattr(self.config, "rig_name", "") or "").strip()
        if configured and not (configured == "test-node-custom" and self.node_id != "test-node-custom"):
            return configured
        return self.node_id

    def log_message(self, format: str, *args: Any) -> None:
        pass

    def _verify_admin_auth(self) -> bool:
        supplied_token = self.headers.get("X-Node-Auth-Token", "")
        authorization = self.headers.get("Authorization", "")
        if not supplied_token and authorization.startswith("Bearer "):
            supplied_token = authorization.removeprefix("Bearer ")
        if not supplied_token:
            for item in str(self.headers.get("Cookie", "")).split(";"):
                name, sep, value = item.strip().partition("=")
                if sep and name == DASHBOARD_SESSION_COOKIE:
                    supplied_token = value.strip()
                    break

        if supplied_token and (
            hmac.compare_digest(supplied_token.strip(), NODE_AUTH_TOKEN.strip())
            or hmac.compare_digest(supplied_token.strip(), DASHBOARD_SESSION_TOKEN.strip())
        ):
            return True
        return False

    def _send_cors_headers(self) -> None:
        """Allow only the known portal origins to call authenticated APIs."""
        origin = str(self.headers.get("Origin", "")).strip()
        if origin in ALLOWED_CORS_ORIGINS:
            self.send_header("Access-Control-Allow-Origin", origin)
            self.send_header("Vary", "Origin")
            self.send_header("Access-Control-Allow-Private-Network", "true")

    def _verify_action_auth(self) -> bool:
        return self._verify_admin_auth()

    def _verify_owner_inference_auth(self) -> bool:
        """Allow the paired fleet owner to use inference on this local node.

        The node token remains mandatory for dashboard and administrative
        actions. A configured owner key is a separate, narrowly scoped LAN
        inference grant so paired clients can use the node without copying a
        node-secret into a phone or URL.
        """
        client_ip = str(getattr(self, "client_address", ("", 0))[0] or "")
        try:
            if not (ipaddress.ip_address(client_ip).is_private or ipaddress.ip_address(client_ip).is_loopback):
                return False
        except ValueError:
            return False
        configured = getattr(self, "config", None)
        if configured is None:
            configured = getattr(DashboardHandler, "config", None)
        configured_key = str(getattr(configured, "owner_key", "") or "").strip()
        if not configured_key:
            return False
        supplied_key = str(self.headers.get("X-Owner-Key", "") or "").strip()
        if not supplied_key:
            authorization = str(self.headers.get("Authorization", "") or "").strip()
            if authorization.startswith("Bearer "):
                supplied_key = authorization.removeprefix("Bearer ").strip()
        return bool(supplied_key) and hmac.compare_digest(supplied_key, configured_key)

    def do_OPTIONS(self) -> None:
        self.send_response(HTTPStatus.OK)
        self._send_cors_headers()
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS, PUT, DELETE")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, Authorization, X-Node-Auth-Token, X-Owner-Key, Accept, X-Requested-With")
        self.send_header("Access-Control-Max-Age", "86400")
        self.send_header("Content-Length", "0")
        self.end_headers()

    def _send_json(self, payload: dict[str, Any], status: HTTPStatus = HTTPStatus.OK) -> None:
        resp = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self._send_cors_headers()
        self.send_header("Content-Length", str(len(resp)))
        self.end_headers()
        self.wfile.write(resp)

    def _send_unauthorized(self) -> None:
        self._send_json(
            {"error": {"message": "Unauthorized: open the dashboard first or provide a valid node authentication header", "code": 401}},
            HTTPStatus.UNAUTHORIZED,
        )

    def do_GET(self) -> None:
        parsed_url = urllib.parse.urlparse(self.path)
        req_path = parsed_url.path

        if ModelManagerHandler.handle_get(self, req_path, parsed_url.query):
            return

        if InferenceRouter.handle_get(self, req_path, APPLIANCE_VERSION):
            return

        if FanControlHandler.handle_get(self, req_path):
            return

        if req_path in ("", "/", "/index.html"):
            html = get_dashboard_html()
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self._send_cors_headers()
            self.send_header("Cache-Control", "no-cache, no-store, must-revalidate")
            self.send_header("Pragma", "no-cache")
            self.send_header("Expires", "0")
            self.end_headers()
            self.wfile.write(html.encode("utf-8"))
            return

        # llama.cpp WebUI & Chat Studio static assets
        clean_path = req_path.rstrip("/")
        if clean_path in ("/webui", "/chat", "/llama") or req_path in ("/webui/", "/chat/", "/llama/"):
            index_target = _safe_resolve_portal_file("webui/index.html")
            if index_target and index_target.exists():
                data = index_target.read_bytes()
                self.send_response(HTTPStatus.OK)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self._send_cors_headers()
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)
                return

        if req_path.startswith("/webui/"):
            sub_rel = req_path.removeprefix("/webui/")
            target_f = _safe_resolve_portal_file(f"webui/{sub_rel}")
            if target_f and target_f.exists():
                suffix = target_f.suffix.lower()
                content_types = {
                    ".html": "text/html; charset=utf-8",
                    ".js": "application/javascript; charset=utf-8",
                    ".mjs": "application/javascript; charset=utf-8",
                    ".css": "text/css; charset=utf-8",
                    ".json": "application/json; charset=utf-8",
                    ".webmanifest": "application/manifest+json; charset=utf-8",
                    ".svg": "image/svg+xml",
                    ".png": "image/png",
                    ".ico": "image/x-icon",
                    ".wasm": "application/wasm",
                }
                ctype = content_types.get(suffix, "application/octet-stream")
                data = target_f.read_bytes()
                self.send_response(HTTPStatus.OK)
                self.send_header("Content-Type", ctype)
                self._send_cors_headers()
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)
                return

        if req_path.startswith("/_app/") or req_path.startswith("/workbox-") or req_path in ("/sw.js", "/build.json", "/manifest.webmanifest"):
            sub_rel = req_path.lstrip("/")
            target_f = _safe_resolve_portal_file(f"webui/{sub_rel}")
            if target_f and target_f.exists():
                suffix = target_f.suffix.lower()
                content_types = {
                    ".html": "text/html; charset=utf-8",
                    ".js": "application/javascript; charset=utf-8",
                    ".mjs": "application/javascript; charset=utf-8",
                    ".css": "text/css; charset=utf-8",
                    ".json": "application/json; charset=utf-8",
                    ".webmanifest": "application/manifest+json; charset=utf-8",
                    ".svg": "image/svg+xml",
                    ".png": "image/png",
                    ".ico": "image/x-icon",
                    ".wasm": "application/wasm",
                }
                ctype = content_types.get(suffix, "application/octet-stream")
                data = target_f.read_bytes()
                self.send_response(HTTPStatus.OK)
                self.send_header("Content-Type", ctype)
                self._send_cors_headers()
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)
                return

        if req_path.startswith("/generated/"):
            sub_rel = req_path.removeprefix("/generated/").lstrip("/\\")
            target_f = _safe_resolve_portal_file(f"generated/{sub_rel}")
            if target_f and target_f.exists():
                suffix = target_f.suffix.lower()
                ctype = "image/png" if suffix == ".png" else "image/jpeg" if suffix in (".jpg", ".jpeg") else "application/octet-stream"
                data = target_f.read_bytes()
                self.send_response(HTTPStatus.OK)
                self.send_header("Content-Type", ctype)
                self._send_cors_headers()
                self.send_header("Cache-Control", "public, max-age=86400")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)
                return

        if KillswitchHandler.handle_get(self, req_path):
            return

        if TelemetryHandler.handle_get(self, req_path):
            return

        if SystemActionsHandler.handle_get(self, req_path, APPLIANCE_VERSION):
            return

        if WebAppsHandler.handle_get(self, req_path):
            return

        self.send_error(HTTPStatus.NOT_FOUND, "Not Found")

    def do_POST(self) -> None:
        parsed_url = urllib.parse.urlparse(self.path)
        req_path = parsed_url.path
        try:
            content_len = int(self.headers.get("Content-Length", 0))
        except (TypeError, ValueError):
            self._send_json({"error": {"message": "Invalid Content-Length", "code": "invalid_request_error"}}, HTTPStatus.BAD_REQUEST)
            return
        if content_len < 0:
            self._send_json({"error": {"message": "Invalid Content-Length", "code": "invalid_request_error"}}, HTTPStatus.BAD_REQUEST)
            return
        if content_len > MAX_REQUEST_BODY_BYTES:
            self._send_json({"error": {"message": "Request body is too large", "code": "request_too_large"}}, HTTPStatus.REQUEST_ENTITY_TOO_LARGE)
            return
        post_body = self.rfile.read(content_len) if content_len > 0 else b"{}"

        # Administrative POST routes require the node token. The paired fleet
        # owner may use only the inference routes with the configured owner
        # key; anonymous LAN callers never reach the agent loop.
        authorized = self._verify_action_auth()
        inference_paths = {
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
            "/api/chat",
            "/api/v1/chat",
            "/api/generate",
            "/api/v1/generate",
        }
        if not authorized and req_path in inference_paths:
            authorized = self._verify_owner_inference_auth()
        if not authorized:
            self._send_unauthorized()
            return

        if ModelManagerHandler.handle_post(self, req_path, post_body):
            return

        if InferenceRouter.handle_post(self, req_path, post_body):
            return

        if FanControlHandler.handle_post(self, req_path, post_body):
            return

        if KillswitchHandler.handle_post(self, req_path, post_body):
            return

        if SystemActionsHandler.handle_post(self, req_path, post_body, APPLIANCE_VERSION):
            return

        self.send_error(HTTPStatus.NOT_FOUND, "Not Found")


class ReusableThreadingHTTPServer(ThreadingHTTPServer):
    allow_reuse_address = True
    daemon_threads = True


def create_dashboard_server(
    host: str = "0.0.0.0",
    port: int = 8080,
    config: ApplianceConfig | None = None,
    inventory: RigInventory | None = None,
    node_id: str = "cm-inference-node-01",
) -> tuple[ThreadingHTTPServer, int]:
    if config is None:
        config = load_appliance_config()
    if inventory is None:
        inventory = scan_rig_hardware_stable()

    effective_node_id = config.rig_name or node_id or "cm-node"
    DashboardHandler.config = config
    DashboardHandler.inventory = inventory
    DashboardHandler.node_id = effective_node_id

    # NodeOS must not rely on zero-RPM driver defaults. The controller is
    # capability-aware and is a no-op on Windows drivers without fan access.
    global FAN_SAFETY_CONTROLLER
    try:
        from tools.appliance.fan_control import FanSafetyController
        FAN_SAFETY_CONTROLLER = FanSafetyController(inventory, config)
        FAN_SAFETY_CONTROLLER.start()
    except Exception as exc:
        log.warning("Fan safety controller unavailable: %s", exc)

    try:
        from services.appliance_dashboard.tunnel_relay import start_cloud_tunnel_relay
        start_cloud_tunnel_relay(node_id=effective_node_id)
    except Exception:
        pass

    server_inst = None
    actual_port = port
    for candidate_port in ([port] if port > 0 else []) + [8080, 8081, 8082, 8083, 8084]:
        try:
            server_inst = ReusableThreadingHTTPServer((host, candidate_port), DashboardHandler)
            actual_port = server_inst.server_address[1]
            break
        except OSError:
            continue

    if server_inst is None:
        server_inst = ReusableThreadingHTTPServer((host, 0), DashboardHandler)
        actual_port = server_inst.server_address[1]

    try:
        from tools.appliance.lan_discovery_responder import start_lan_discovery_responder
        gpu_name = inventory.gpus[0].model_name if getattr(inventory, "gpus", None) else "ComputeMesh AI Node"
        start_lan_discovery_responder(node_id=effective_node_id, port=actual_port, gpu_summary=gpu_name)
    except Exception:
        pass

    try:
        GLOBAL_MESH_AGGREGATOR.start()
    except Exception:
        pass

    return server_inst, actual_port


def run_dashboard_server(
    host: str = "0.0.0.0",
    port: int = 8080,
    config: ApplianceConfig | None = None,
    inventory: RigInventory | None = None,
    node_id: str = "cm-inference-node-01",
) -> int:
    GLOBAL_MESH_AGGREGATOR.start()
    server, actual_port = create_dashboard_server(host, port, config, inventory, node_id)
    try:
        if sys.stdout is not None:
            print(f"ComputeMesh Appliance Dashboard running at http://{host}:{actual_port}")
    except Exception:
        pass

    try:
        server.serve_forever()
    except Exception:
        pass
    finally:
        try:
            server.server_close()
        except Exception:
            pass
    return actual_port


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="ComputeMesh Appliance Web Dashboard")
    parser.add_argument("--host", default="0.0.0.0", help="Host address to bind (default: 0.0.0.0)")
    parser.add_argument("--port", type=int, default=8080, help="Port to listen on (default: 8080)")
    args = parser.parse_args(argv)

    run_dashboard_server(host=args.host, port=args.port)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
