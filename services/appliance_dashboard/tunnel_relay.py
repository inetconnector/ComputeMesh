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


class NodeAuthTokenStorageError(RuntimeError):
    """Raised when the persistent node token cannot be read or durably stored."""


def _atomic_secure_text_write(path: Path, value: str) -> None:
    """Write one node credential atomically without accepting a failed persist."""
    path = Path(path)
    if path.is_symlink() or path.parent.is_symlink():
        raise NodeAuthTokenStorageError(f"refusing symlinked node token path: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    if sys.platform != "win32":
        path.parent.chmod(0o700)

    temp_path = path.with_name(f"{path.name}.tmp.{secrets.token_hex(8)}")
    fd = os.open(temp_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(value)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_path, path)
        if sys.platform != "win32":
            os.chmod(path, 0o600)
            dir_fd = os.open(path.parent, os.O_RDONLY)
            try:
                os.fsync(dir_fd)
            finally:
                os.close(dir_fd)
    except Exception as exc:
        try:
            temp_path.unlink(missing_ok=True)
        except OSError:
            pass
        if isinstance(exc, NodeAuthTokenStorageError):
            raise
        raise NodeAuthTokenStorageError(f"cannot durably persist node token: {path}") from exc


def get_or_create_node_auth_token(search_paths: list[Path] | None = None) -> str:
    """Retrieve or create a persistent node authentication token using high-entropy random secrets.

    Searches across authorized permissioned storage tiers:
    1. State storage directory (/var/lib/computemesh/node_auth_token.txt)
    2. User home directory (~/.computemesh/node_auth_token.txt)
    3. Appliance configuration directory (/etc/computemesh/node_auth_token.txt)

    Security Boundaries:
    - Never derives secrets deterministically from machine/hardware identifiers.
    - Never persists secrets to FAT32 boot partitions (/boot or /live/image).
    - Enforces strict 0600 file permissions on POSIX.
    """
    if search_paths is None:
        candidate_paths = [
            Path("/var/lib/computemesh/node_auth_token.txt"),
            Path.home() / ".computemesh" / "node_auth_token.txt",
            Path("/etc/computemesh/node_auth_token.txt"),
        ]
        persist_targets = candidate_paths
    else:
        candidate_paths = search_paths
        persist_targets = search_paths

    for p in candidate_paths:
        p = Path(p)
        if p.is_symlink() or (p.exists() and not p.is_file()):
            raise NodeAuthTokenStorageError(f"node token path is not a regular file: {p}")
        if p.exists():
            try:
                tok = p.read_text(encoding="utf-8").strip()
            except Exception as exc:
                raise NodeAuthTokenStorageError(f"cannot read persistent node token: {p}") from exc
            if not tok or not tok.startswith("cm_tunnel_") or not tok[10:].isalnum():
                raise NodeAuthTokenStorageError(f"persistent node token is invalid: {p}")
            return tok

    # Generate a cryptographically secure random token with high entropy
    new_token = "cm_tunnel_" + secrets.token_hex(24)

    # Persist the token to one accessible permissioned storage location.  A
    # failed write is not success: returning this value would rotate identity
    # on every reboot and orphan the node at the coordinator.
    last_error: Exception | None = None
    for target in persist_targets:
        try:
            _atomic_secure_text_write(Path(target), new_token)
            return new_token
        except Exception as exc:
            last_error = exc

    raise NodeAuthTokenStorageError("cannot persist node authentication token") from last_error


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
        from tools.security.node_key_storage import get_or_create_node_private_key
        from cryptography.hazmat.primitives import serialization
        self._private_key, self._key_path = get_or_create_node_private_key()
        raw_pub = self._private_key.public_key().public_bytes(
            serialization.Encoding.Raw,
            serialization.PublicFormat.Raw,
        )
        self.public_key_hex = raw_pub.hex()
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
        # Peak values inferred from a product name are not measurements.
        return 0.0

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
            try:
                from tools.appliance.hardware_detector import read_all_thermals
                gpu_thermals = [item.to_dict() for item in read_all_thermals(inv)]
            except Exception:
                gpu_thermals = []
            try:
                from services.appliance_dashboard.model_manager import get_model_manager
                model_runtime = get_model_manager().status().get("engine", {})
            except Exception as exc:
                model_runtime = {"state": "unavailable", "ready": False, "last_error": str(exc)}
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
                "compute_measurement": "unavailable",
                "gpu_thermals": gpu_thermals,
                "model_runtime": model_runtime,
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

        now_ts = int(time.time())
        heartbeat_nonce = secrets.token_urlsafe(18)
        from tools.security.node_key_storage import sign_node_heartbeat
        sig_b64u = sign_node_heartbeat(
            self._private_key,
            self.node_id,
            self.auth_token,
            now_ts,
            nonce=heartbeat_nonce,
            previous_node_id=previous_node_id or "",
        )

        payload: dict[str, Any] = {
            "node_id": self.node_id,
            "previous_node_id": previous_node_id or "",
            "auth_token": self.auth_token,
            "owner_key": owner_key,
            "payout_address": payout_address,
            "public_key": getattr(self, "public_key_hex", ""),
            "signature": sig_b64u,
            "timestamp": now_ts,
            "nonce": heartbeat_nonce,
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
                "compute_measurement": "unavailable",
                "gpu_thermals": gpu_thermals,
                "model_runtime": model_runtime,
                "is_simulated": False,
            },
            "global_mesh": gm,
            "machine_identity": (
                __import__("services.identity.machine_identity", fromlist=["collect_machine_identity"])
                .collect_machine_identity()
                .to_public_dict()
                if "services.identity.machine_identity" in sys.modules or True
                else {}
            ),
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
