"""ComputeMesh Android Mobile Edge Node Relay & Simulator.

Emulates the Android mobile background service lifecycle, zero-drain battery guards,
MiniCPM5-2B hardware capability reporting, and token heartbeats.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import logging
import os
from pathlib import Path
import sys
import time
from typing import Any
import urllib.request

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from services.common.config import CONFIG

logger = logging.getLogger("ComputeMesh-Android-Relay")
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")


class AndroidBatteryPolicy:
    def __init__(
        self,
        is_charging: bool = True,
        battery_pct: int = 95,
        temperature_celsius: float = 28.5,
        is_wifi_connected: bool = True,
        max_allowed_temp: float = 42.0,
    ) -> None:
        self.is_charging = is_charging
        self.battery_pct = battery_pct
        self.temperature_celsius = temperature_celsius
        self.is_wifi_connected = is_wifi_connected
        self.max_allowed_temp = max_allowed_temp

    def evaluate(self, allow_unplugged: bool = False) -> tuple[bool, str | None]:
        if self.temperature_celsius >= self.max_allowed_temp:
            return False, f"Temperature too high ({self.temperature_celsius}°C >= {self.max_allowed_temp}°C)"
        if not self.is_charging and not allow_unplugged:
            return False, "Device not connected to AC charger"
        if not self.is_charging and allow_unplugged and self.battery_pct < 80:
            return False, f"Battery percentage below 80% ({self.battery_pct}%)"
        if not self.is_wifi_connected:
            return False, "Not connected to unmetered Wi-Fi"
        return True, None


class AndroidNodeRelay:
    def __init__(
        self,
        gateway_url: str = "http://127.0.0.1:8000",
        node_id: str = "android-snapdragon-01",
        owner_key: str = "",
        auth_token: str = "",
    ) -> None:
        self.gateway_url = gateway_url.rstrip("/")
        self.node_id = node_id
        self.owner_key = owner_key
        self.auth_token = auth_token or f"cm_mobile_{node_id.replace('-', '_')}"
        self.battery_guard = AndroidBatteryPolicy()
        self.tokens_processed = 0

    def build_heartbeat_payload(self) -> dict[str, Any]:
        permitted, reason = self.battery_guard.evaluate()
        now_iso = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")

        return {
            "node_id": self.node_id,
            "auth_token": self.auth_token,
            "owner_key": self.owner_key,
            "inventory": {
                "schema_version": 1,
                "captured_at": now_iso,
                "host_architecture": "android_arm64",
                "total_gpus": 0,
                "total_vram_bytes": 0,
                "gpus": [],
                "battery_level": self.battery_guard.battery_pct,
                "is_charging": self.battery_guard.is_charging,
                "temperature_c": self.battery_guard.temperature_celsius,
                "soc_model": "Qualcomm Snapdragon 8 Gen 3 (ARMv9)",
                "ram_total_bytes": 12 * (1024**3),
            },
            "telemetry": {
                "tokens_processed": self.tokens_processed,
                "earnings_cm": self.tokens_processed,
                "local_compute_tflops": 2.2,
                "is_simulated": False,
                "is_compute_permitted": permitted,
                "restriction_reason": reason or "",
            },
            "global_mesh": {},
            "software": {
                "model": "openbmb/minicpm5-2b",
                "quantization": "Q4_K_M",
                "engine": "llama.cpp-ndk-arm64",
                "version": "1.2.142",
                "client": "ComputeMesh-Android",
            },
        }

    def send_heartbeat(self) -> dict[str, Any]:
        payload = self.build_heartbeat_payload()
        url = f"{self.gateway_url}/api/v1/node/heartbeat"
        data = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(
            url,
            data=data,
            headers={
                "Content-Type": "application/json",
                "User-Agent": "ComputeMesh-Android-Node/1.2",
            },
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            body = resp.read().decode("utf-8")
            return json.loads(body) if body else {}


def main() -> None:
    parser = argparse.ArgumentParser(description="ComputeMesh Android Node Relay")
    parser.add_argument("--gateway", default="https://mesh.inetconnector.com", help="Gateway URL")
    parser.add_argument("--node-id", default="android-galaxy-s24", help="Node ID")
    parser.add_argument("--owner-key", default="", help="Owner key for fleet binding")
    parser.add_argument("--interval", type=int, default=10, help="Heartbeat interval in seconds")
    args = parser.parse_args()

    relay = AndroidNodeRelay(gateway_url=args.gateway, node_id=args.node_id, owner_key=args.owner_key)
    logger.info("Starting Android Node Relay for %s connecting to %s", args.node_id, args.gateway)

    while True:
        try:
            resp = relay.send_heartbeat()
            logger.info("Heartbeat acknowledged: %s", resp)
        except Exception as exc:
            logger.error("Heartbeat error: %s", exc)
        time.sleep(args.interval)


if __name__ == "__main__":
    main()
