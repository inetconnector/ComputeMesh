"""ComputeMesh Embedded Appliance Web Dashboard Server.

Clean, modular HTTP server providing local/remote web dashboard and JSON APIs.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import subprocess
import sys
from typing import Any
import urllib.parse

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from tools.appliance.appliance_config import (
    ApplianceConfig,
    load_appliance_config,
    save_system_config,
)
from tools.appliance.hardware_detector import (
    RigInventory,
    scan_rig_hardware,
)

from config import CONFIG
from services.appliance_dashboard.template_loader import get_dashboard_html
from services.appliance_dashboard.network import get_network_interfaces
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

APPLIANCE_VERSION = CONFIG.appliance_version


class DashboardHandler(BaseHTTPRequestHandler):
    config: ApplianceConfig
    inventory: RigInventory
    node_id: str
    tokens_served: int = 142050
    earnings_cm: float = 47.35

    def log_message(self, format: str, *args: Any) -> None:
        pass

    def do_OPTIONS(self) -> None:
        self.send_response(HTTPStatus.OK)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()

    def do_GET(self) -> None:
        parsed_url = urllib.parse.urlparse(self.path)
        req_path = parsed_url.path

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

        if req_path == "/api/status":
            thermals = []
            local_tflops = 0.0
            for g in self.inventory.gpus:
                m_lower = g.model_name.lower()
                if "4090" in m_lower:
                    tf = 82.6
                elif "3080" in m_lower or "3090" in m_lower:
                    tf = 24.0
                elif "mi25" in m_lower or "vega" in m_lower:
                    tf = 24.6
                elif "6800" in m_lower or "6900" in m_lower or "7900" in m_lower:
                    tf = 32.0
                elif "intel" in m_lower:
                    tf = 1.0
                else:
                    tf = round(max(1.0, (g.vram_bytes / (1024**3)) * 1.5), 1)
                local_tflops += tf

                thermals.append({
                    "gpu_index": g.index,
                    "temp": 56 + (g.index * 2) % 12,
                    "fan": 60 + (g.index * 3) % 20,
                    "power_watts": 110 + (g.index * 5) % 30,
                    "tflops": tf,
                })

            local_payload = {
                "node_id": getattr(self.config, "rig_name", None) or self.node_id,
                "inventory": self.inventory.to_dict(),
                "telemetry": {
                    "tokens_processed": self.tokens_served,
                    "earnings_cm": self.earnings_cm,
                    "local_compute_tflops": round(local_tflops, 1),
                },
            }
            mesh_stats = GLOBAL_MESH_AGGREGATOR.get_mesh_stats(local_payload)

            current_node_id = getattr(self.config, "rig_name", None) or self.node_id
            payload = {
                "node_id": current_node_id,
                "auth_token": NODE_AUTH_TOKEN,
                "config": self.config.to_dict() if hasattr(self.config, "to_dict") else {},
                "inventory": self.inventory.to_dict(),
                "network": {
                    "interfaces": get_network_interfaces(node_id=current_node_id, auth_token=NODE_AUTH_TOKEN),
                },
                "global_mesh": mesh_stats,
                "telemetry": {
                    "tokens_processed": self.tokens_served,
                    "earnings_cm": self.earnings_cm,
                    "local_compute_tflops": round(local_tflops, 1),
                    "gpu_thermals": thermals,
                    "uptime_seconds": 86400,
                },
                "software": {
                    "current_version": APPLIANCE_VERSION,
                    "update_url": CONFIG.endpoints.update_manifest_url,
                },
            }
            body = json.dumps(payload).encode("utf-8")
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", "application/json")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.send_header("Cache-Control", "no-cache, no-store, must-revalidate")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return

        if req_path == "/api/action/check_update":
            try:
                for candidate in [Path("/opt/computemesh"), Path("/root/ComputeMesh"), REPO_ROOT]:
                    if candidate.exists() and str(candidate) not in sys.path:
                        sys.path.insert(0, str(candidate))

                from services.updater.auto_updater import AutoUpdater
                updater = AutoUpdater(current_version=APPLIANCE_VERSION)
                u_info = updater.check_for_updates()
                if u_info:
                    resp_dict = {
                        "update_available": u_info.is_newer,
                        "version": u_info.version,
                        "current_version": APPLIANCE_VERSION,
                        "release_date": u_info.release_date,
                        "filename": u_info.filename,
                    }
                else:
                    resp_dict = {"update_available": False, "version": APPLIANCE_VERSION, "current_version": APPLIANCE_VERSION}
                resp = json.dumps(resp_dict).encode("utf-8")
                self.send_response(HTTPStatus.OK)
                self.send_header("Content-Type", "application/json")
                self.send_header("Access-Control-Allow-Origin", "*")
                self.send_header("Content-Length", str(len(resp)))
                self.end_headers()
                self.wfile.write(resp)
            except Exception as e:
                err_resp = json.dumps({"status": "error", "message": str(e)}).encode("utf-8")
                self.send_response(HTTPStatus.INTERNAL_SERVER_ERROR)
                self.send_header("Content-Type", "application/json")
                self.send_header("Access-Control-Allow-Origin", "*")
                self.send_header("Content-Length", str(len(err_resp)))
                self.end_headers()
                self.wfile.write(err_resp)
            return

        self.send_error(HTTPStatus.NOT_FOUND, "Not Found")

    def do_POST(self) -> None:
        parsed_url = urllib.parse.urlparse(self.path)
        req_path = parsed_url.path
        content_len = int(self.headers.get("Content-Length", 0))
        post_body = self.rfile.read(content_len) if content_len > 0 else b"{}"

        if req_path == "/api/config":
            try:
                data = json.loads(post_body.decode("utf-8"))
                new_dict = self.config.to_dict()
                for k, v in data.items():
                    if k in new_dict:
                        new_dict[k] = v

                updated_cfg = ApplianceConfig(**new_dict)
                save_system_config(updated_cfg)
                DashboardHandler.config = updated_cfg

                resp = json.dumps({"status": "ok", "message": "Configuration saved successfully"}).encode("utf-8")
                self.send_response(HTTPStatus.OK)
                self.send_header("Content-Type", "application/json")
                self.send_header("Access-Control-Allow-Origin", "*")
                self.send_header("Content-Length", str(len(resp)))
                self.end_headers()
                self.wfile.write(resp)
            except Exception as e:
                err_resp = json.dumps({"status": "error", "message": str(e)}).encode("utf-8")
                self.send_response(HTTPStatus.BAD_REQUEST)
                self.send_header("Content-Type", "application/json")
                self.send_header("Access-Control-Allow-Origin", "*")
                self.send_header("Content-Length", str(len(err_resp)))
                self.end_headers()
                self.wfile.write(err_resp)
            return

        if req_path == "/api/action/restart_daemon":
            subprocess.Popen(["sh", "-c", "sleep 1 && systemctl restart computemesh-appliance.service computemesh-dashboard.service computemesh-node.service || true"], stderr=subprocess.DEVNULL)
            resp = json.dumps({"status": "ok", "message": "Daemon restarting"}).encode("utf-8")
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", "application/json")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.send_header("Content-Length", str(len(resp)))
            self.end_headers()
            self.wfile.write(resp)
            return

        if req_path == "/api/action/reboot":
            subprocess.Popen(["systemctl", "reboot"], stderr=subprocess.DEVNULL)
            resp = json.dumps({"status": "ok", "message": "Rebooting system"}).encode("utf-8")
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", "application/json")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.send_header("Content-Length", str(len(resp)))
            self.end_headers()
            self.wfile.write(resp)
            return

        if req_path == "/api/action/os_upgrade":
            try:
                subprocess.Popen(
                    ["bash", "-c", "apt-get update -qq && DEBIAN_FRONTEND=noninteractive apt-get upgrade -y -qq"],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
                resp = json.dumps({"status": "ok", "message": "OS package upgrade running in background"}).encode("utf-8")
                self.send_response(HTTPStatus.OK)
                self.send_header("Content-Type", "application/json")
                self.send_header("Access-Control-Allow-Origin", "*")
                self.send_header("Content-Length", str(len(resp)))
                self.end_headers()
                self.wfile.write(resp)
            except Exception as e:
                err_resp = json.dumps({"status": "error", "message": str(e)}).encode("utf-8")
                self.send_response(HTTPStatus.INTERNAL_SERVER_ERROR)
                self.send_header("Content-Type", "application/json")
                self.send_header("Access-Control-Allow-Origin", "*")
                self.send_header("Content-Length", str(len(err_resp)))
                self.end_headers()
                self.wfile.write(err_resp)
            return

        if req_path == "/api/action/apply_update":
            try:
                for candidate in [Path("/opt/computemesh"), Path("/root/ComputeMesh"), REPO_ROOT]:
                    if candidate.exists() and str(candidate) not in sys.path:
                        sys.path.insert(0, str(candidate))

                from services.updater.auto_updater import AutoUpdater
                updater = AutoUpdater(current_version=APPLIANCE_VERSION)
                u_info = updater.check_for_updates()
                if u_info:
                    pkg = updater.download_and_verify(u_info)
                    updater.apply_linux_update(pkg)
                    resp = json.dumps({"status": "ok", "message": f"Updated to v{u_info.version}"}).encode("utf-8")
                else:
                    resp = json.dumps({"status": "ok", "message": "Already up to date"}).encode("utf-8")
                self.send_response(HTTPStatus.OK)
                self.send_header("Content-Type", "application/json")
                self.send_header("Access-Control-Allow-Origin", "*")
                self.send_header("Content-Length", str(len(resp)))
                self.end_headers()
                self.wfile.write(resp)
            except Exception as e:
                err_resp = json.dumps({"status": "error", "message": str(e)}).encode("utf-8")
                self.send_response(HTTPStatus.BAD_REQUEST)
                self.send_header("Content-Type", "application/json")
                self.send_header("Access-Control-Allow-Origin", "*")
                self.send_header("Content-Length", str(len(err_resp)))
                self.end_headers()
                self.wfile.write(err_resp)
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
        inventory = scan_rig_hardware()

    DashboardHandler.config = config
    DashboardHandler.inventory = inventory
    DashboardHandler.node_id = node_id

    for candidate_port in [port, 8080, 8081, 8082, 8083, 8084]:
        try:
            server = ReusableThreadingHTTPServer((host, candidate_port), DashboardHandler)
            return server, candidate_port
        except OSError:
            continue

    server = ReusableThreadingHTTPServer((host, 0), DashboardHandler)
    return server, server.server_address[1]


def run_dashboard_server(
    host: str = "0.0.0.0",
    port: int = 8080,
    config: ApplianceConfig | None = None,
    inventory: RigInventory | None = None,
    node_id: str = "cm-inference-node-01",
) -> int:
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
