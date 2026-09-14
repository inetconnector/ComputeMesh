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
from tools.appliance.hardware_detector import scan_rig_hardware, collect_hardware_debug

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
            handler.send_header("Access-Control-Allow-Origin", "*")
            handler.send_header("Content-Length", str(len(resp)))
            handler.end_headers()
            handler.wfile.write(resp)
            return True

        if req_path == "/api/status":
            thermals = []
            local_tflops = 0.0
            for g in handler.inventory.gpus:
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
                    "local_compute_tflops": round(local_tflops, 1),
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
            handler.send_response(HTTPStatus.OK)
            handler.send_header("Content-Type", "application/json")
            handler.send_header("Access-Control-Allow-Origin", "*")
            handler.send_header("Cache-Control", "no-cache, no-store, must-revalidate")
            handler.send_header("Content-Length", str(len(body)))
            handler.end_headers()
            handler.wfile.write(body)
            return True

        return False
