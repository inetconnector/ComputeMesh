"""ComputeMesh Appliance Dashboard Cloud Tunnel Relay & Node Authentication."""
from __future__ import annotations

import json
import os
from pathlib import Path
import secrets
import sys
import threading
import time
from typing import Any
import urllib.request

from config import CONFIG


def get_or_create_node_auth_token() -> str:
    token_file = Path.home() / ".computemesh" / "node_auth_token.txt"
    try:
        if token_file.exists():
            token = token_file.read_text(encoding="utf-8").strip()
            if token:
                return token
    except Exception:
        pass
    new_token = "cm_tunnel_" + secrets.token_hex(16)
    try:
        token_file.parent.mkdir(parents=True, exist_ok=True)
        token_file.write_text(new_token, encoding="utf-8")
    except Exception:
        pass
    return new_token


NODE_AUTH_TOKEN = get_or_create_node_auth_token()


def get_default_node_id() -> str:
    try:
        from tools.appliance.appliance_config import load_appliance_config
        cfg = load_appliance_config()
        if getattr(cfg, "rig_name", "") and getattr(cfg, "rig_name", "") not in ("cm-inference-node-01", "test-node-custom"):
            return cfg.rig_name
    except Exception:
        pass
    import socket
    try:
        raw_host = socket.gethostname().lower().replace("_", "-").strip()
    except Exception:
        raw_host = "node"
    if sys.platform == "win32":
        return f"cm-win-{raw_host}"
    if "trixie" in raw_host or "srv" in raw_host or "supersrv" in raw_host:
        return "supersrv-trixie"
    return f"cm-node-{raw_host}"


class CloudTunnelRelay:
    def __init__(self, node_id: str | None = None, auth_token: str | None = None) -> None:
        self.node_id = node_id or get_default_node_id()
        self.auth_token = auth_token or NODE_AUTH_TOKEN
        self._running = True
        self._thread = threading.Thread(target=self._worker, daemon=True)
        self._thread.start()

    def _calculate_tflops(self, inv: Any) -> float:
        total_tf = 0.0
        for gpu in getattr(inv, "gpus", []):
            m = gpu.model_name.lower()
            if "4090" in m:
                tf = 82.6
            elif "3080" in m or "3090" in m:
                tf = 24.0
            elif "mi25" in m or "vega" in m:
                tf = 24.6
            elif "6800" in m or "6900" in m or "7900" in m:
                tf = 32.0
            elif "intel" in m:
                tf = 1.0
            else:
                tf = round(max(1.0, (gpu.vram_bytes / (1024**3)) * 1.5), 1)
            total_tf += tf
        return round(total_tf, 1)

    def _worker(self) -> None:
        while self._running:
            try:
                from tools.appliance.hardware_detector import scan_rig_hardware
                from services.appliance_dashboard.mesh_aggregator import GLOBAL_MESH_AGGREGATOR

                inv = scan_rig_hardware()
                tf = self._calculate_tflops(inv)
                local_vram_gb = round(inv.total_vram_bytes / (1024**3), 1)
                local_payload = {
                    "node_id": self.node_id,
                    "status": "online",
                    "inventory": inv.to_dict(),
                    "telemetry": {
                        "tokens_processed": 0,
                        "earnings_cm": 0.0,
                        "local_compute_tflops": tf,
                        "gpu_thermals": [{"temp": 56, "fan": 60, "power_watts": 110}],
                        "is_simulated": False,
                    },
                }
                gm = GLOBAL_MESH_AGGREGATOR.get_mesh_stats(local_payload)
                if not gm.get("total_vram_gb") and local_vram_gb > 0:
                    gm["total_vram_gb"] = local_vram_gb
                if not gm.get("total_compute_tflops") and tf > 0:
                    gm["total_compute_tflops"] = tf
                if not gm.get("total_nodes_online"):
                    gm["total_nodes_online"] = 1

                payload = {
                    "node_id": self.node_id,
                    "auth_token": self.auth_token,
                    "inventory": inv.to_dict(),
                    "telemetry": {
                        "tokens_processed": 0,
                        "earnings_cm": 0.0,
                        "local_compute_tflops": tf,
                        "gpu_thermals": [{"temp": 56, "fan": 60, "power_watts": 110}],
                        "is_simulated": False,
                    },
                    "global_mesh": gm,
                }
                data = json.dumps(payload).encode("utf-8")
                req = urllib.request.Request(
                    CONFIG.endpoints.heartbeat_url,
                    data=data,
                    headers={"Content-Type": "application/json", "User-Agent": "ComputeMesh-Node-Relay/1.2"},
                )
                urllib.request.urlopen(req, timeout=3.0)
            except Exception:
                pass
            time.sleep(5)


CLOUD_TUNNEL_RELAY: CloudTunnelRelay | None = None


def start_cloud_tunnel_relay(node_id: str | None = None, auth_token: str | None = None) -> CloudTunnelRelay:
    global CLOUD_TUNNEL_RELAY
    if CLOUD_TUNNEL_RELAY is None:
        CLOUD_TUNNEL_RELAY = CloudTunnelRelay(node_id=node_id, auth_token=auth_token)
    return CLOUD_TUNNEL_RELAY

