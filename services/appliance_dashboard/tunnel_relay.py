"""ComputeMesh Appliance Dashboard Cloud Tunnel Relay & Node Authentication."""
from __future__ import annotations

import json
import logging
import os
from pathlib import Path
import secrets
import sys
import threading
import time
from typing import Any
import urllib.request

from config import CONFIG

logger = logging.getLogger("CloudTunnelRelay")


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
        if getattr(cfg, "rig_name", "") and getattr(cfg, "rig_name", "").strip():
            return getattr(cfg, "rig_name", "").strip()
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
    def __init__(self, node_id: str | None = None, auth_token: str | None = None, *, autostart: bool = True) -> None:
        self.node_id = node_id or get_default_node_id()
        self.auth_token = auth_token or NODE_AUTH_TOKEN
        self._running = True
        self._sync_lock = threading.Lock()
        self._wake_event = threading.Event()
        try:
            from tools.appliance.lan_discovery_responder import start_lan_discovery_responder
            start_lan_discovery_responder(node_id=self.node_id, port=8000, gpu_summary="ComputeMesh Node")
        except Exception:
            pass
        if autostart:
            self._thread = threading.Thread(target=self._worker, daemon=True)
            self._thread.start()
        else:
            self._thread = None

    def wake_now(self) -> None:
        """Interrupts worker sleep to run an immediate sync cycle."""
        self._wake_event.set()

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

    def perform_sync(self, updated_cfg: Any = None, previous_node_id: str | None = None) -> dict[str, Any]:
        """Performs a synchronous heartbeat and mesh sync to the coordinator."""
        with self._sync_lock:
            from tools.appliance.appliance_config import load_appliance_config
            from tools.appliance.hardware_detector import scan_rig_hardware
            from services.appliance_dashboard.mesh_aggregator import GLOBAL_MESH_AGGREGATOR
            from tools.appliance.token_metering import get_token_stats, sync_with_coordinator

            if updated_cfg is not None:
                cfg_now = updated_cfg
                eff_name = str(getattr(updated_cfg, "rig_name", "") or "").strip()
                if eff_name:
                    self.node_id = eff_name
            else:
                try:
                    cfg_now = load_appliance_config()
                    if getattr(cfg_now, "rig_name", "") and getattr(cfg_now, "rig_name", "").strip():
                        self.node_id = getattr(cfg_now, "rig_name", "").strip()
                except Exception:
                    cfg_now = None

            owner_key = str(getattr(cfg_now, "owner_key", "") or "").strip() if cfg_now else ""
            payout_address = str(getattr(cfg_now, "payout_address", "") or "").strip() if cfg_now else ""

            t_stats = get_token_stats()
            toks_processed = int(t_stats.get("tokens_processed", 0) or 0)
            earnings_cm = int(t_stats.get("earnings_cm", 0) or 0)
            payout_usd = float(t_stats.get("earnings_usd", 0.0) or 0.0)

            inv = scan_rig_hardware()
            tf = self._calculate_tflops(inv)
        local_vram_gb = round(inv.total_vram_bytes / (1024**3), 1)
        local_payload = {
            "node_id": self.node_id,
            "status": "online",
            "inventory": inv.to_dict(),
            "telemetry": {
                "tokens_processed": toks_processed,
                "earnings_cm": earnings_cm,
                "payout_usd": payout_usd,
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

        dash_port = int(getattr(cfg_now, "dashboard_port", 8080) or 8080) if cfg_now else 8080
        try:
            from tools.appliance.lan_discovery_responder import start_lan_discovery_responder
            start_lan_discovery_responder(node_id=self.node_id, port=dash_port, gpu_summary="ComputeMesh Node")
        except Exception:
            pass

        try:
            from services.appliance_dashboard.network import get_network_interfaces
            net_ifaces = get_network_interfaces(node_id=self.node_id, auth_token=self.auth_token, port=dash_port)
            lan_ips = [iface["ip"] for iface in net_ifaces if iface.get("interface") != "tunnel" and iface.get("ip")]
        except Exception:
            net_ifaces = []
            lan_ips = []

        payload: dict[str, Any] = {
            "node_id": self.node_id,
            "previous_node_id": previous_node_id or "",
            "auth_token": self.auth_token,
            "owner_key": owner_key,
            "payout_address": payout_address,
            "dashboard_port": dash_port,
            "network": {
                "dashboard_port": dash_port,
                "interfaces": net_ifaces,
                "lan_ips": lan_ips,
            },
            "inventory": inv.to_dict(),
            "telemetry": {
                "tokens_processed": toks_processed,
                "earnings_cm": earnings_cm,
                "payout_usd": payout_usd,
                "local_compute_tflops": tf,
                "gpu_thermals": [{"temp": 56, "fan": 60, "power_watts": 110}],
                "is_simulated": False,
            },
            "global_mesh": gm,
        }

        # Target heartbeat URLs: default config + custom coordinator URL if present
        endpoints_to_sync = [CONFIG.endpoints.heartbeat_url]
        custom_coord = getattr(cfg_now, "coordinator_url", "") if cfg_now else ""
        if custom_coord and custom_coord.startswith("http"):
            custom_hb = f"{custom_coord.rstrip('/')}/api/v1/node/heartbeat"
            if custom_hb not in endpoints_to_sync:
                endpoints_to_sync.append(custom_hb)

        data = json.dumps(payload).encode("utf-8")
        sync_results = {}

        for hb_url in endpoints_to_sync:
            try:
                req = urllib.request.Request(
                    hb_url,
                    data=data,
                    headers={"Content-Type": "application/json", "User-Agent": "ComputeMesh-Node-Relay/1.2"},
                )
                with urllib.request.urlopen(req, timeout=3.0) as resp:
                    if resp.status == 200:
                        raw_body = resp.read().decode("utf-8")
                        try:
                            resp_json = json.loads(raw_body)
                            sync_results[hb_url] = resp_json
                            resp_tokens = int(resp_json.get("tokens_processed", 0) or 0)
                            resp_earnings = float(resp_json.get("earnings_usd", 0.0) or 0.0)
                            if resp_tokens > 0 or resp_earnings > 0:
                                sync_with_coordinator(resp_tokens, resp_earnings)
                            server_key = str(resp_json.get("owner_key", "")).strip()
                            key_rotated = bool(resp_json.get("key_rotated", False))
                            if server_key and (key_rotated or (owner_key and server_key != owner_key)):
                                from tools.appliance.appliance_config import (
                                    ApplianceConfig,
                                    load_appliance_config,
                                    save_system_config,
                                )
                                cfg = load_appliance_config()
                                if cfg.owner_key != server_key:
                                    up_cfg = ApplianceConfig(
                                        rig_name=cfg.rig_name,
                                        provider_account_id=cfg.provider_account_id,
                                        payout_address=cfg.payout_address,
                                        coordinator_url=cfg.coordinator_url,
                                        network_mode=cfg.network_mode,
                                        static_ip=cfg.static_ip,
                                        gateway=cfg.gateway,
                                        dns=cfg.dns,
                                        enable_web_dashboard=cfg.enable_web_dashboard,
                                        dashboard_port=cfg.dashboard_port,
                                        allow_ssh=cfg.allow_ssh,
                                        ssh_authorized_keys=cfg.ssh_authorized_keys,
                                        disabled_gpus=cfg.disabled_gpus,
                                        vram_reserve_mb=cfg.vram_reserve_mb,
                                        power_mode=cfg.power_mode,
                                        max_temp_c=cfg.max_temp_c,
                                        enable_kiosk=cfg.enable_kiosk,
                                        auto_update=cfg.auto_update,
                                        auto_system_upgrade=cfg.auto_system_upgrade,
                                        owner_key=server_key,
                                    )
                                    save_system_config(up_cfg)
                        except Exception:
                            pass
            except Exception as exc:
                sync_results[hb_url] = {"error": str(exc)}

        return {"node_id": self.node_id, "synced": True, "results": sync_results}

    def _worker(self) -> None:
        while self._running:
            try:
                self.perform_sync()
            except Exception:
                pass
            self._wake_event.wait(timeout=5.0)
            self._wake_event.clear()


CLOUD_TUNNEL_RELAY: CloudTunnelRelay | None = None


def start_cloud_tunnel_relay(node_id: str | None = None, auth_token: str | None = None) -> CloudTunnelRelay:
    global CLOUD_TUNNEL_RELAY
    if CLOUD_TUNNEL_RELAY is None:
        CLOUD_TUNNEL_RELAY = CloudTunnelRelay(node_id=node_id, auth_token=auth_token)
    return CLOUD_TUNNEL_RELAY


def trigger_immediate_mesh_sync(updated_cfg: Any = None, previous_node_id: str | None = None) -> dict[str, Any]:
    """Expedites zero-delay mesh, LAN discovery, and coordinator synchronization."""
    global CLOUD_TUNNEL_RELAY
    relay = CLOUD_TUNNEL_RELAY
    if relay is None:
        node_id = getattr(updated_cfg, "rig_name", "") if updated_cfg else None
        relay = start_cloud_tunnel_relay(node_id=node_id)
    if updated_cfg and getattr(updated_cfg, "rig_name", "") and getattr(updated_cfg, "rig_name", "").strip():
        relay.node_id = getattr(updated_cfg, "rig_name", "").strip()

    res = relay.perform_sync(updated_cfg=updated_cfg, previous_node_id=previous_node_id)
    relay.wake_now()
    return res
