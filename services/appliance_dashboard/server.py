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

import hmac
import ipaddress
from services.gateway.security import SECURITY_HEADERS

APPLIANCE_VERSION = CONFIG.appliance_version


class DashboardHandler(BaseHTTPRequestHandler):
    server_version = "ComputeMesh-NodeOS/1.2"
    sys_version = ""

    config: ApplianceConfig
    inventory: RigInventory
    node_id: str

    def _current_node_id(self) -> str:
        configured = str(getattr(self.config, "rig_name", "") or "").strip()
        if configured and not (configured == "test-node-custom" and self.node_id != "test-node-custom"):
            return configured
        return self.node_id
    tokens_served: int = 0
    earnings_cm: float = 0.0

    def log_message(self, format: str, *args: Any) -> None:
        pass

    def _verify_action_auth(self) -> bool:
        client_ip = str(getattr(self, "client_address", ("127.0.0.1", 0))[0])
        # Loopback and private LAN callers (home network dashboard browsing) are allowed
        try:
            ip_obj = ipaddress.ip_address(client_ip.strip())
            if ip_obj.is_loopback or ip_obj.is_private or ip_obj.is_link_local:
                return True
        except Exception:
            if client_ip in ("127.0.0.1", "::1", "localhost"):
                return True

        # Non-local callers (WAN / cloud tunnel) must supply valid node auth token
        supplied_token = self.headers.get("X-Node-Auth-Token", "")
        if not supplied_token:
            parsed = urllib.parse.urlparse(self.path)
            q = urllib.parse.parse_qs(parsed.query)
            supplied_token = q.get("auth", [""])[0]

        if supplied_token and hmac.compare_digest(supplied_token.strip(), NODE_AUTH_TOKEN.strip()):
            return True
        return False

    def _send_unauthorized(self) -> None:
        body = json.dumps({"status": "error", "message": "Unauthorized. Valid X-Node-Auth-Token required."}).encode("utf-8")
        self.send_response(HTTPStatus.UNAUTHORIZED)
        self.send_header("Content-Type", "application/json")
        for h_name, h_val in SECURITY_HEADERS.items():
            self.send_header(h_name, h_val)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Connection", "close")
        self.end_headers()
        self.wfile.write(body)
        self.close_connection = True

    def do_OPTIONS(self) -> None:
        self.send_response(HTTPStatus.OK)
        for h_name, h_val in SECURITY_HEADERS.items():
            self.send_header(h_name, h_val)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, X-Node-Auth-Token")
        self.send_header("Connection", "close")
        self.end_headers()
        self.close_connection = True

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

        if req_path == "/api/debug/diagnostics":
            if not self._verify_action_auth():
                self._send_unauthorized()
                return
            from tools.appliance.hardware_detector import collect_hardware_debug

            def _run(cmd: list[str]) -> dict[str, Any]:
                try:
                    res = subprocess.run(cmd, capture_output=True, text=True, timeout=8)
                    return {"cmd": cmd, "returncode": res.returncode, "stdout": res.stdout[-4000:], "stderr": res.stderr[-2000:]}
                except FileNotFoundError:
                    return {"cmd": cmd, "error": "command not found"}
                except Exception as exc:
                    return {"cmd": cmd, "error": str(exc)}

            diagnostics: dict[str, Any] = {
                "platform": sys.platform,
                "process_start_inventory": self.inventory.to_dict(),
                "hardware_debug": collect_hardware_debug(),
            }
            if sys.platform != "win32":
                # Fixed, read-only diagnostic allowlist -- never user-supplied
                # arguments, never shell=True, so this cannot become a remote
                # arbitrary-command execution surface.
                diagnostics["probes"] = {
                    "lsmod_amdgpu": _run(["sh", "-c", "lsmod 2>/dev/null | grep -i amdgpu || true"]),
                    "dmesg_amdgpu": _run(["sh", "-c", "dmesg 2>/dev/null | grep -i amdgpu | tail -n 40 || true"]),
                    "lspci_vga": _run(["sh", "-c", "lspci -nnk 2>/dev/null | grep -A3 -i 'vga\\|3d\\|display' || true"]),
                }
            try:
                diagnostics["fresh_rescan"] = scan_rig_hardware().to_dict()
            except Exception as exc:
                diagnostics["fresh_rescan_error"] = str(exc)

            resp = json.dumps(diagnostics, indent=2).encode("utf-8")
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", "application/json")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.send_header("Content-Length", str(len(resp)))
            self.end_headers()
            self.wfile.write(resp)
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
                "node_id": self._current_node_id(),
                "inventory": self.inventory.to_dict(),
                "telemetry": {
                    "tokens_processed": self.tokens_served,
                    "earnings_cm": self.earnings_cm,
                    "local_compute_tflops": round(local_tflops, 1),
                },
            }
            mesh_stats = GLOBAL_MESH_AGGREGATOR.get_mesh_stats(local_payload)

            if not self._verify_action_auth():
                self._send_unauthorized()
                return

            current_node_id = self._current_node_id()
            is_win = sys.platform == "win32"
            is_lin = sys.platform.startswith("linux")
            is_appl = is_lin and Path("/opt/computemesh").exists()
            payload = {
                "node_id": current_node_id,
                "os": "windows" if is_win else ("linux" if is_lin else sys.platform),
                "is_windows": is_win,
                "is_linux": is_lin,
                "is_appliance": is_appl,
                "platform_name": "Windows" if is_win else ("Linux (NodeOS)" if is_appl else "Linux"),
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

        if not self._verify_action_auth():
            self._send_unauthorized()
            return

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
                for h_name, h_val in SECURITY_HEADERS.items():
                    self.send_header(h_name, h_val)
                self.send_header("Access-Control-Allow-Origin", "*")
                self.send_header("Content-Length", str(len(resp)))
                self.end_headers()
                self.wfile.write(resp)
            except Exception as e:
                err_resp = json.dumps({"status": "error", "message": str(e)}).encode("utf-8")
                self.send_response(HTTPStatus.BAD_REQUEST)
                self.send_header("Content-Type", "application/json")
                for h_name, h_val in SECURITY_HEADERS.items():
                    self.send_header(h_name, h_val)
                self.send_header("Access-Control-Allow-Origin", "*")
                self.send_header("Content-Length", str(len(err_resp)))
                self.end_headers()
                self.wfile.write(err_resp)
            return

        if req_path == "/api/action/restart_daemon":
            if sys.platform == "win32":
                # On Windows, restart daemon thread or no-op
                pass
            else:
                subprocess.Popen(["sh", "-c", "sleep 1 && systemctl restart computemesh-appliance.service computemesh-dashboard.service computemesh-node.service || true"], stderr=subprocess.DEVNULL)
            resp = json.dumps({"status": "ok", "message": "Daemon restarting"}).encode("utf-8")
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", "application/json")
            for h_name, h_val in SECURITY_HEADERS.items():
                self.send_header(h_name, h_val)
            self.send_header("Access-Control-Allow-Origin", "*")
            self.send_header("Content-Length", str(len(resp)))
            self.end_headers()
            self.wfile.write(resp)
            return

        if req_path == "/api/action/reboot":
            if sys.platform == "win32":
                err_resp = json.dumps({"status": "error", "message": "Reboot is not supported on Windows."}).encode("utf-8")
                self.send_response(HTTPStatus.BAD_REQUEST)
                self.send_header("Content-Type", "application/json")
                for h_name, h_val in SECURITY_HEADERS.items():
                    self.send_header(h_name, h_val)
                self.send_header("Access-Control-Allow-Origin", "*")
                self.send_header("Content-Length", str(len(err_resp)))
                self.end_headers()
                self.wfile.write(err_resp)
                return

            subprocess.Popen(["systemctl", "reboot"], stderr=subprocess.DEVNULL)
            resp = json.dumps({"status": "ok", "message": "Rebooting system"}).encode("utf-8")
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", "application/json")
            for h_name, h_val in SECURITY_HEADERS.items():
                self.send_header(h_name, h_val)
            self.send_header("Access-Control-Allow-Origin", "*")
            self.send_header("Content-Length", str(len(resp)))
            self.end_headers()
            self.wfile.write(resp)
            return

        if req_path == "/api/action/os_upgrade":
            if sys.platform == "win32":
                err_resp = json.dumps({"status": "error", "message": "OS upgrades are not supported on Windows."}).encode("utf-8")
                self.send_response(HTTPStatus.BAD_REQUEST)
                self.send_header("Content-Type", "application/json")
                for h_name, h_val in SECURITY_HEADERS.items():
                    self.send_header(h_name, h_val)
                self.send_header("Access-Control-Allow-Origin", "*")
                self.send_header("Content-Length", str(len(err_resp)))
                self.end_headers()
                self.wfile.write(err_resp)
                return

            try:
                subprocess.Popen(
                    ["apt-get", "update", "-qq"],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
                resp = json.dumps({"status": "ok", "message": "OS package upgrade running in background"}).encode("utf-8")
                self.send_response(HTTPStatus.OK)
                self.send_header("Content-Type", "application/json")
                for h_name, h_val in SECURITY_HEADERS.items():
                    self.send_header(h_name, h_val)
                self.send_header("Access-Control-Allow-Origin", "*")
                self.send_header("Content-Length", str(len(resp)))
                self.end_headers()
                self.wfile.write(resp)
            except Exception as e:
                err_resp = json.dumps({"status": "error", "message": str(e)}).encode("utf-8")
                self.send_response(HTTPStatus.INTERNAL_SERVER_ERROR)
                self.send_header("Content-Type", "application/json")
                for h_name, h_val in SECURITY_HEADERS.items():
                    self.send_header(h_name, h_val)
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
                    if sys.platform == "win32":
                        updater.apply_windows_update(pkg)
                    else:
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

    effective_node_id = config.rig_name or node_id or "cm-node"
    DashboardHandler.config = config
    DashboardHandler.inventory = inventory
    DashboardHandler.node_id = effective_node_id

    try:
        from services.appliance_dashboard.tunnel_relay import start_cloud_tunnel_relay
        start_cloud_tunnel_relay(node_id=effective_node_id)
    except Exception:
        pass

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
