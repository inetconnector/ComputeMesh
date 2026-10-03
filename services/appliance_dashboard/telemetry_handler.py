"""Appliance Telemetry, GPU Metrics, and Diagnostics Handlers."""
from __future__ import annotations

from http import HTTPStatus
import json
import logging
import os
from pathlib import Path
import subprocess
import sys
from typing import Any

from config import CONFIG
from services.appliance_dashboard.network import get_network_interfaces
from services.appliance_dashboard.mesh_aggregator import GLOBAL_MESH_AGGREGATOR
from services.appliance_dashboard.tunnel_relay import NODE_AUTH_TOKEN
from tools.appliance.hardware_detector import collect_hardware_debug, read_all_thermals, scan_rig_hardware

log = logging.getLogger("computemesh.appliance.telemetry")
APPLIANCE_VERSION = CONFIG.appliance_version


class TelemetryHandler:
    """Handles status telemetry, GPU metrics, thermals, and system diagnostics."""

    @staticmethod
    def handle_get(handler: Any, req_path: str) -> bool:
        if req_path == "/api/debug/diagnostics":
            if not handler._verify_action_auth():
                handler._send_unauthorized()
                return True

            def _run(cmd: list[str]) -> dict[str, Any]:
                try:
                    res = subprocess.run(cmd, capture_output=True, text=True, timeout=8)
                    return {"cmd": cmd, "returncode": res.returncode, "stdout": res.stdout[-4000:], "stderr": res.stderr[-2000:]}
                except FileNotFoundError:
                    return {"cmd": cmd, "error": "command not found"}
                except Exception as exc:
                    return {"cmd": cmd, "error": str(exc)}

            def _file_probe(p: Path) -> dict[str, Any]:
                info: dict[str, Any] = {"path": str(p), "exists": p.exists()}
                if info["exists"]:
                    try:
                        st = p.stat()
                        info["mtime"] = st.st_mtime
                        info["size"] = st.st_size
                        info["content"] = json.loads(p.read_text(encoding="utf-8"))
                    except Exception as exc:
                        info["read_error"] = str(exc)
                return info

            diagnostics: dict[str, Any] = {
                "platform": sys.platform,
                "process_start_inventory": handler.inventory.to_dict(),
                "hardware_debug": collect_hardware_debug(),
                "config_persistence": {
                    "env_HOME": os.environ.get("HOME"),
                    "resolved_home": str(Path.home()),
                    "pid": os.getpid(),
                    "system_config": _file_probe(Path("/etc/computemesh/config.json")),
                    "user_config": _file_probe(Path.home() / ".computemesh" / "provider_config.json"),
                },
            }
            if sys.platform != "win32":
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
            handler.send_response(HTTPStatus.OK)
            handler.send_header("Content-Type", "application/json")
            handler._send_cors_headers()
            handler.send_header("Content-Length", str(len(resp)))
            handler.end_headers()
            handler.wfile.write(resp)
            return True

        if req_path == "/api/status":
            measured_thermals = {item.gpu_index: item for item in read_all_thermals(handler.inventory)}
            thermals = []
            for g in handler.inventory.gpus:
                measured = measured_thermals.get(g.index)
                thermals.append({
                    "gpu_index": g.index,
                    "temp": measured.temperature_celsius if measured else None,
                    "fan": measured.fan_speed_percent if measured else None,
                    "power_watts": measured.power_watts if measured else None,
                    "tflops": None,
                })

            t_toks = handler.tokens_served
            t_earn = handler.earnings_cm
            try:
                from tools.appliance.token_metering import get_token_stats
                t_stats = get_token_stats()
                t_toks = max(t_toks, int(t_stats.get("tokens_processed", 0) or 0))
                t_earn = max(t_earn, float(t_stats.get("earnings_cm", 0.0) or 0.0))
            except Exception:
                pass

            local_payload = {
                "node_id": handler._current_node_id(),
                "inventory": handler.inventory.to_dict(),
                "telemetry": {
                    "tokens_processed": t_toks,
                    "earnings_cm": t_earn,
                    "local_compute_tflops": 0.0,
                    "compute_measurement": "unavailable",
                },
            }
            mesh_stats = GLOBAL_MESH_AGGREGATOR.get_mesh_stats(local_payload)

            if not handler._verify_action_auth():
                handler._send_unauthorized()
                return True

            current_node_id = handler._current_node_id()
            is_win = sys.platform == "win32"
            is_lin = sys.platform.startswith("linux")
            is_appl = is_lin and Path("/opt/computemesh").exists()
            uptime_seconds = None
            try:
                if sys.platform.startswith("linux"):
                    uptime_seconds = int(float(Path("/proc/uptime").read_text(encoding="ascii").split()[0]))
                elif sys.platform == "win32":
                    import ctypes
                    uptime_seconds = int(ctypes.windll.kernel32.GetTickCount64() // 1000)
            except Exception:
                pass
            try:
                from services.appliance_dashboard.model_manager import get_model_manager
                model_runtime = get_model_manager().status()
            except Exception as exc:
                model_runtime = {"engine": {"state": "unavailable", "ready": False, "last_error": str(exc)}, "models": []}
            try:
                from tools.appliance.fan_control import fan_status
                fan_runtime = fan_status(handler.inventory, handler.config)
            except Exception as exc:
                fan_runtime = {"control_available": False, "supported_modes": ["auto"], "message": str(exc), "gpus": []}
            payload = {
                "node_id": current_node_id,
                "os": "windows" if is_win else ("linux" if is_lin else sys.platform),
                "is_windows": is_win,
                "is_linux": is_lin,
                "is_appliance": is_appl,
                "platform_name": "Windows" if is_win else ("Linux (NodeOS)" if is_appl else "Linux"),
                "config": handler.config.to_dict() if hasattr(handler.config, "to_dict") else {},
                "inventory": handler.inventory.to_dict(),
                "network": {
                    "interfaces": get_network_interfaces(node_id=current_node_id, auth_token=NODE_AUTH_TOKEN),
                },
                "global_mesh": mesh_stats,
                "telemetry": {
                    "tokens_processed": t_toks,
                    "earnings_cm": t_earn,
                    "local_compute_tflops": 0.0,
                    "compute_measurement": "unavailable",
                    "gpu_thermals": thermals,
                    "fan_control": fan_runtime,
                    "uptime_seconds": uptime_seconds,
                },
                "model_runtime": model_runtime,
                "software": {
                    "current_version": APPLIANCE_VERSION,
                    "update_url": CONFIG.endpoints.update_manifest_url,
                },
            }
            body = json.dumps(payload).encode("utf-8")
            handler.send_response(HTTPStatus.OK)
            handler.send_header("Content-Type", "application/json")
            handler._send_cors_headers()
            handler.send_header("Cache-Control", "no-cache, no-store, must-revalidate")
            handler.send_header("Content-Length", str(len(body)))
            handler.end_headers()
            handler.wfile.write(body)
            return True

        if req_path in ("/api/lan/nodes", "/api/lan/scan"):
            if not handler._verify_action_auth():
                handler._send_unauthorized()
                return True
            try:
                from tools.appliance.lan_discovery_scanner import discover_lan_nodes
                payload = {"nodes": discover_lan_nodes(force=req_path.endswith("/scan")), "scan_scope": "local_private_lan"}
                handler._send_json(payload)
            except Exception as exc:
                handler._send_json({"error": str(exc), "nodes": []}, HTTPStatus.INTERNAL_SERVER_ERROR)
            return True

        return False
