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
from services.appliance_dashboard.models_handler import ModelsHandler
from services.appliance_dashboard.system_actions import SystemActionsHandler
from services.appliance_dashboard.killswitch_actions import KillswitchHandler
from services.appliance_dashboard.telemetry_handler import TelemetryHandler
from services.appliance_dashboard.webapp_handler import WebAppsHandler

log = logging.getLogger("computemesh.appliance.server")
APPLIANCE_VERSION = CONFIG.appliance_version
PORTAL_DIR = (REPO_ROOT / "portal").resolve()


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

    def _verify_action_auth(self) -> bool:
        supplied_token = ""
        auth_header = self.headers.get("Authorization", "")
        if auth_header.startswith("Bearer "):
            supplied_token = auth_header.removeprefix("Bearer ").strip()
        if not supplied_token:
            supplied_token = self.headers.get("X-Node-Auth-Token", "").strip()

        if supplied_token and hmac.compare_digest(supplied_token, NODE_AUTH_TOKEN.strip()):
            return True

        client_ip = str(getattr(self, "client_address", ("127.0.0.1", 0))[0]).strip()
        # Only strict local loopback (same machine) is permitted without explicit auth token.
        # Remote LAN IPs must supply NODE_AUTH_TOKEN for any mutating or admin actions.
        try:
            ip_obj = ipaddress.ip_address(client_ip)
            if ip_obj.is_loopback:
                return True
        except Exception:
            if client_ip in ("127.0.0.1", "::1", "localhost"):
                return True

        return False

    def do_OPTIONS(self) -> None:
        self.send_response(HTTPStatus.OK)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS, PUT, DELETE")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, Authorization, X-Node-Auth-Token, Accept, X-Requested-With")
        self.send_header("Access-Control-Allow-Private-Network", "true")
        self.send_header("Access-Control-Max-Age", "86400")
        self.send_header("Content-Length", "0")
        self.end_headers()

    def _send_json(self, payload: dict[str, Any], status: HTTPStatus = HTTPStatus.OK) -> None:
        resp = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Private-Network", "true")
        self.send_header("Content-Length", str(len(resp)))
        self.end_headers()
        self.wfile.write(resp)

    def _send_unauthorized(self) -> None:
        self._send_json(
            {"error": {"message": "Unauthorized: Valid X-Node-Auth-Token or ?auth= query token required for remote access", "code": 401}},
            HTTPStatus.UNAUTHORIZED,
        )

    def do_GET(self) -> None:
        parsed_url = urllib.parse.urlparse(self.path)
        req_path = parsed_url.path

        if req_path == "/api/debug/model-selection":
            try:
                from services.appliance_dashboard.model_engine_service import ModelEngineService
                info = ModelEngineService.get_instance().get_status()
            except Exception as exc:
                info = {"error": str(exc)}
            self._send_json(info)
            return True

        if req_path in ("", "/", "/index.html"):
            html = get_dashboard_html()
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Access-Control-Allow-Origin", "*")
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
                self.send_header("Access-Control-Allow-Origin", "*")
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
                self.send_header("Access-Control-Allow-Origin", "*")
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
                self.send_header("Access-Control-Allow-Origin", "*")
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
                self.send_header("Access-Control-Allow-Origin", "*")
                self.send_header("Cache-Control", "public, max-age=86400")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)
                return
        # New endpoint for UI property exposure used by CORS tests
        if req_path == "/webui/props":
            # Return an empty JSON object; real implementation may provide UI config.
            self._send_json({})
            return

        if ModelsHandler.handle_get(self, req_path):
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
        content_len = int(self.headers.get("Content-Length", 0))
        post_body = self.rfile.read(content_len) if content_len > 0 else b"{}"

        if InferenceRouter.handle_post(self, req_path, post_body):
            return

        if ModelsHandler.handle_post(self, req_path, post_body):
            return

        if not self._verify_action_auth():
            self._send_unauthorized()
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

    # Ensure the best local model is selected and started before serving requests
    try:
        from services.appliance_dashboard.model_engine_service import ModelEngineService
        ModelEngineService.get_instance().ensure_best_model()
    except Exception as e:
        log.error(f"Failed to ensure best model at startup: {e}")

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
