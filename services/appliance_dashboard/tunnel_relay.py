"""ComputeMesh Appliance Dashboard Cloud Tunnel Relay & Node Authentication."""
from __future__ import annotations

import json
import os
from pathlib import Path
import secrets
import threading
import time
from typing import Any
import urllib.request


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


class CloudTunnelRelay:
    def __init__(self, node_id: str = "cm-laptop-node", auth_token: str | None = None) -> None:
        self.node_id = node_id
        self.auth_token = auth_token or NODE_AUTH_TOKEN
        self._running = True
        self._thread = threading.Thread(target=self._worker, daemon=True)
        self._thread.start()

    def _worker(self) -> None:
        while self._running:
            try:
                from tools.appliance.hardware_detector import scan_rig_hardware
                from services.appliance_dashboard.mesh_aggregator import GLOBAL_MESH_AGGREGATOR

                inv = scan_rig_hardware()
                gm = GLOBAL_MESH_AGGREGATOR.get_mesh_stats()
                payload = {
                    "node_id": self.node_id,
                    "auth_token": self.auth_token,
                    "inventory": inv.to_dict(),
                    "telemetry": {
                        "tokens_processed": 142050,
                        "earnings_cm": 0.0016,
                        "local_compute_tflops": 24.0,
                        "gpu_thermals": [{"temp": 56, "fan": 60, "power_watts": 110}],
                    },
                    "global_mesh": gm,
                }
                data = json.dumps(payload).encode("utf-8")
                req = urllib.request.Request(
                    "https://computemesh.inetconnector.com/api/v1/node/heartbeat",
                    data=data,
                    headers={"Content-Type": "application/json", "User-Agent": "ComputeMesh-Node-Relay/1.2"},
                )
                urllib.request.urlopen(req, timeout=3.0)
            except Exception:
                pass
            time.sleep(5)


CLOUD_TUNNEL_RELAY = CloudTunnelRelay(node_id="cm-laptop-node", auth_token=NODE_AUTH_TOKEN)
