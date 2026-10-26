"""ComputeMesh Appliance Dashboard Cloud Tunnel Relay & Node Authentication."""
from __future__ import annotations

import json
import logging
import os
from functools import wraps
from pathlib import Path
import secrets
import sys
import threading
import time
from typing import Any
import urllib.request

from config import CONFIG
from tools.appliance.node_identity import (
    NodeIdentityError,
    dashboard_must_not_start_relay,
    is_nodeos_mode,
    migrate_enrolled_node_id,
    read_enrolled_node_id,
    resolve_enrolled_private_key_path,
    resolve_node_id,
)

logger = logging.getLogger("CloudTunnelRelay")


def _serialize_sync_call(method):
    """Keep the entire heartbeat construction and network send single-flight."""

    @wraps(method)
    def wrapped(self, *args, **kwargs):
        with self._sync_lock:
            return method(self, *args, **kwargs)

    return wrapped


from tools.security import node_auth_token_storage as _node_auth_storage
from tools.security.node_auth_token_storage import (
    NodeAuthTokenStorageError,
    atomic_secure_text_write as _atomic_secure_text_write,
    default_node_auth_paths as _default_node_auth_paths,
    read_existing_node_auth_token as _read_existing_node_auth_token,
)


def _nodeos_mode() -> bool:
    return is_nodeos_mode()


def nodeos_provider_ready() -> bool:
    """Return true only after the durable NodeOS preflight marker exists."""
    if not _nodeos_mode():
        return True
    marker = Path(
        os.environ.get(
            "COMPUTEMESH_NODEOS_PREFLIGHT_MARKER",
            "/run/computemesh/node-preflight.ok",
        )
    )
    provider_env = Path(
        os.environ.get("COMPUTEMESH_PROVIDER_ENV", "/etc/computemesh/provider.env")
    )
    return marker.is_file() and not marker.is_symlink() and provider_env.is_file() and not provider_env.is_symlink()


def get_or_create_node_auth_token(search_paths: list[Path] | None = None) -> str:
    """Compatibility wrapper retaining the old dashboard import contract."""
    return _node_auth_storage.get_or_create_node_auth_token(
        search_paths,
        atomic_writer=_atomic_secure_text_write,
    )


def persist_node_auth_token(token: str, path: Path | None = None) -> Path:
    """Compatibility wrapper for callers outside the enrollment module."""
    return _node_auth_storage.persist_node_auth_token(
        token,
        path,
        atomic_writer=_atomic_secure_text_write,
    )


def _load_import_token() -> str:
    existing = _read_existing_node_auth_token()
    if existing is not None:
        return existing
    if _nodeos_mode():
        # The dashboard remains available for local enrollment, but it must
        # not mint a credential before the persistent provider preflight.
        return ""
    return get_or_create_node_auth_token()


NODE_AUTH_TOKEN = _load_import_token()


def get_default_node_id() -> str:
    # An enrolled provider.env is authoritative.  Do not let a boot template,
    # mutable dashboard config, or hostname create a second identity after a
    # reboot.
    persisted = read_enrolled_node_id()
    if persisted is not None:
        return persisted
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
        if _nodeos_mode() and not nodeos_provider_ready():
            raise NodeAuthTokenStorageError(
                "NodeOS provider preflight is not ready; refusing to start heartbeat identity"
            )
        try:
            configured_node_id = node_id or get_default_node_id()
            self.node_id = resolve_node_id(configured_node_id)
        except NodeIdentityError as exc:
            raise NodeAuthTokenStorageError(str(exc)) from exc
        self.auth_token = auth_token or NODE_AUTH_TOKEN
        if not self.auth_token:
            self.auth_token = get_or_create_node_auth_token()
        self._running = True
        # perform_sync retains an inner compatibility lock around the local
        # collection section; RLock lets the outer call-wide guard hold the
        # lock through payload signing and all network sends as well.
        self._sync_lock = threading.RLock()
        self._wake_event = threading.Event()
        from tools.security.node_key_storage import get_or_create_node_private_key
        from cryptography.hazmat.primitives import serialization
        try:
            if _nodeos_mode():
                enrolled_key_path = resolve_enrolled_private_key_path()
                self._private_key, self._key_path = get_or_create_node_private_key(
                    path=enrolled_key_path,
                    allow_generate=False,
                )
            else:
                self._private_key, self._key_path = get_or_create_node_private_key(
                    allow_generate=True,
                )
        except NodeIdentityError as exc:
            raise NodeAuthTokenStorageError(str(exc)) from exc
        except Exception as exc:  # noqa: BLE001 - fail closed without exposing key details
            message = str(exc).strip() or "persistent enrolled node private key is unavailable"
            raise NodeAuthTokenStorageError(message) from exc
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

    @_serialize_sync_call
    def perform_sync(
        self,
        updated_cfg: Any = None,
        previous_node_id: str | None = None,
        *,
        authorize_node_id_migration: bool = False,
    ) -> dict[str, Any]:
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
                    persisted_node_id = read_enrolled_node_id()
                    if persisted_node_id is not None and eff_name != persisted_node_id:
                        if not authorize_node_id_migration or previous_node_id != persisted_node_id:
                            raise NodeAuthTokenStorageError(
                                "enrolled node identity changes require an authorized migration"
                            )
                        try:
                            migrate_enrolled_node_id(
                                eff_name,
                                previous_node_id=persisted_node_id,
                            )
                        except NodeIdentityError as exc:
                            raise NodeAuthTokenStorageError(str(exc)) from exc
                    try:
                        self.node_id = resolve_node_id(eff_name)
                    except NodeIdentityError as exc:
                        raise NodeAuthTokenStorageError(str(exc)) from exc
            else:
                try:
                    cfg_now = load_appliance_config()
                except Exception:
                    cfg_now = None

            configured_node_id = (
                str(getattr(cfg_now, "rig_name", "") or "").strip()
                if cfg_now
                else self.node_id
            ) or self.node_id
            try:
                self.node_id = resolve_node_id(
                    configured_node_id,
                    require_enrolled=_nodeos_mode(),
                )
            except NodeIdentityError as exc:
                raise NodeAuthTokenStorageError(str(exc)) from exc

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

    def stop(self) -> None:
        self._running = False
        self._wake_event.set()
        thread = self._thread
        if thread is not None and thread.is_alive() and thread is not threading.current_thread():
            thread.join(timeout=2.0)


CLOUD_TUNNEL_RELAY: CloudTunnelRelay | None = None


def start_cloud_tunnel_relay(node_id: str | None = None, auth_token: str | None = None) -> CloudTunnelRelay:
    global CLOUD_TUNNEL_RELAY
    if _nodeos_mode() and not nodeos_provider_ready():
        raise NodeAuthTokenStorageError(
            "NodeOS provider preflight is not ready; heartbeat relay is disabled"
        )
    if CLOUD_TUNNEL_RELAY is None:
        CLOUD_TUNNEL_RELAY = CloudTunnelRelay(node_id=node_id, auth_token=auth_token)
    elif node_id:
        try:
            requested = resolve_node_id(node_id)
        except NodeIdentityError as exc:
            raise NodeAuthTokenStorageError(str(exc)) from exc
        if requested != CLOUD_TUNNEL_RELAY.node_id:
            raise NodeAuthTokenStorageError(
                "a second relay cannot use a different node identity"
            )
    return CLOUD_TUNNEL_RELAY


def trigger_immediate_mesh_sync(
    updated_cfg: Any = None,
    previous_node_id: str | None = None,
    *,
    authorize_node_id_migration: bool = False,
) -> dict[str, Any]:
    """Expedites zero-delay mesh, LAN discovery, and coordinator synchronization."""
    global CLOUD_TUNNEL_RELAY
    relay = CLOUD_TUNNEL_RELAY
    if relay is None:
        node_id = getattr(updated_cfg, "rig_name", "") if updated_cfg else None
        relay = start_cloud_tunnel_relay(node_id=node_id)
    res = relay.perform_sync(
        updated_cfg=updated_cfg,
        previous_node_id=previous_node_id,
        authorize_node_id_migration=authorize_node_id_migration,
    )
    relay.wake_now()
    return res
