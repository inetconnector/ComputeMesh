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
from services.appliance_dashboard.system_actions import SystemActionsHandler
from services.appliance_dashboard.killswitch_actions import KillswitchHandler
from services.appliance_dashboard.telemetry_handler import TelemetryHandler
from services.appliance_dashboard.webapp_handler import WebAppsHandler

log = logging.getLogger("computemesh.appliance.server")
APPLIANCE_VERSION = CONFIG.appliance_version


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
        client_ip = str(getattr(self, "client_address", ("127.0.0.1", 0))[0])
        try:
            ip_obj = ipaddress.ip_address(client_ip.strip())
            if ip_obj.is_loopback or ip_obj.is_private or ip_obj.is_link_local:
                return True
        except Exception:
            if client_ip in ("127.0.0.1", "::1", "localhost"):
                return True

        supplied_token = self.headers.get("X-Node-Auth-Token", "")
        if not supplied_token:
            parsed = urllib.parse.urlparse(self.path)
            q = urllib.parse.parse_qs(parsed.query)
            supplied_token = q.get("auth", [""])[0]

        if supplied_token and hmac.compare_digest(supplied_token.strip(), NODE_AUTH_TOKEN.strip()):
            return True
        return False

    def _send_json(self, payload: dict[str, Any], status: HTTPStatus = HTTPStatus.OK) -> None:
        resp = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Access-Control-Allow-Origin", "*")
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

        if InferenceRouter.handle_get(self, req_path, APPLIANCE_VERSION):
            return

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
