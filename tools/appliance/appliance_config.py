#!/usr/bin/env python3
"""ComputeMesh Appliance Configuration Loader & Manager.

Parses node configuration from the FAT32 boot partition (/boot/computemesh.env),
local system configuration (/etc/computemesh/config.json), or environment variables.
Supports runtime updates for payout addresses, per-GPU compute enablement,
thermal throttle limits, and power management profiles.
"""
from __future__ import annotations

import argparse
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import sys
from typing import Any

from config import CONFIG

DEFAULT_BOOT_CONFIG = Path("/boot/computemesh.env")
DEFAULT_LIVE_BOOT_CONFIG = Path("/live/image/computemesh.env")
DEFAULT_SYSTEM_CONFIG = Path("/etc/computemesh/config.json")


@dataclass(frozen=True)
class ApplianceConfig:
    rig_name: str
    provider_account_id: str
    payout_address: str
    coordinator_url: str
    network_mode: str  # "dhcp" or "static"
    static_ip: str | None
    gateway: str | None
    dns: str | None
    enable_web_dashboard: bool
    dashboard_port: int
    allow_ssh: bool
    ssh_authorized_keys: str | None
    disabled_gpus: list[int] = field(default_factory=list)
    vram_reserve_mb: int = 512
    power_mode: str = "balanced"  # "eco", "balanced", "max"
    max_temp_c: int = 80
    enable_kiosk: bool = True
    auto_update: bool = True
    auto_system_upgrade: bool = True

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _parse_env_file(path: Path) -> dict[str, str]:
    result: dict[str, str] = {}
    if not path.exists():
        return result
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" in line:
            k, v = line.split("=", 1)
            result[k.strip()] = v.strip().strip('"').strip("'")
    return result


def load_appliance_config(
    boot_path: Path = DEFAULT_BOOT_CONFIG,
    system_path: Path = DEFAULT_SYSTEM_CONFIG,
) -> ApplianceConfig:
    """Load appliance configuration from boot partition, falling back to system config & defaults."""
    env_vars = _parse_env_file(boot_path)
    if not env_vars and DEFAULT_LIVE_BOOT_CONFIG.exists():
        env_vars = _parse_env_file(DEFAULT_LIVE_BOOT_CONFIG)
    
    system_data: dict[str, Any] = {}
    if system_path.exists():
        try:
            system_data = json.loads(system_path.read_text(encoding="utf-8"))
        except Exception:
            pass

    user_cfg = Path.home() / ".computemesh" / "provider_config.json"
    if user_cfg.exists():
        try:
            system_data.update(json.loads(user_cfg.read_text(encoding="utf-8")))
        except Exception:
            pass

    rig_name = (
        env_vars.get("NODE_NAME")
        or env_vars.get("RIG_NAME")
        or system_data.get("rig_name")
        or os.environ.get("RIG_NAME")
        or "cm-inference-node-01"
    )
    provider_account = (
        env_vars.get("PROVIDER_ACCOUNT_ID")
        or system_data.get("provider_account_id")
        or os.environ.get("PROVIDER_ACCOUNT_ID")
        or "cm_provider_genesis"
    )
    payout_address = (
        env_vars.get("WALLET_PAYOUT_ADDRESS")
        or env_vars.get("PAYOUT_ADDRESS")
        or system_data.get("payout_address")
        or os.environ.get("WALLET_PAYOUT_ADDRESS")
        or ""
    )
    if payout_address == "0x0000000000000000000000000000000000000000":
        payout_address = ""
    coordinator_url = (
        env_vars.get("COORDINATOR_URL")
        or system_data.get("coordinator_url")
        or os.environ.get("COORDINATOR_URL")
        or CONFIG.endpoints.base_url
    )
    network_mode = env_vars.get("NETWORK_MODE") or system_data.get("network_mode") or "dhcp"
    static_ip = env_vars.get("STATIC_IP") or system_data.get("static_ip")
    gateway = env_vars.get("GATEWAY") or system_data.get("gateway")
    dns = env_vars.get("DNS") or system_data.get("dns")
    
    enable_web = env_vars.get("ENABLE_WEB_DASHBOARD", "true").lower() in ("true", "1", "yes")
    dash_port = int(env_vars.get("DASHBOARD_PORT") or system_data.get("dashboard_port") or 8080)
    allow_ssh = env_vars.get("ALLOW_SSH", "true").lower() in ("true", "1", "yes")
    ssh_keys = env_vars.get("SSH_AUTHORIZED_KEYS") or system_data.get("ssh_authorized_keys")

    # Parse disabled GPUs
    disabled_gpus: list[int] = []
    if "DISABLED_GPUS" in env_vars:
        try:
            disabled_gpus = [int(x.strip()) for x in env_vars["DISABLED_GPUS"].split(",") if x.strip().isdigit()]
        except Exception:
            pass
    elif "disabled_gpus" in system_data and isinstance(system_data["disabled_gpus"], list):
        disabled_gpus = [int(x) for x in system_data["disabled_gpus"] if isinstance(x, (int, str)) and str(x).isdigit()]

    vram_reserve = int(env_vars.get("VRAM_RESERVE_MB") or system_data.get("vram_reserve_mb") or 512)
    power_mode = env_vars.get("POWER_MODE") or system_data.get("power_mode") or "balanced"
    max_temp = int(env_vars.get("MAX_TEMP_C") or system_data.get("max_temp_c") or 80)
    enable_kiosk = env_vars.get("ENABLE_KIOSK", "true").lower() in ("true", "1", "yes")
    auto_update = env_vars.get("AUTO_UPDATE", "true").lower() in ("true", "1", "yes") if "AUTO_UPDATE" in env_vars else system_data.get("auto_update", True)
    auto_sys_upgrade = env_vars.get("AUTO_SYSTEM_UPGRADE", "true").lower() in ("true", "1", "yes") if "AUTO_SYSTEM_UPGRADE" in env_vars else system_data.get("auto_system_upgrade", True)

    return ApplianceConfig(
        rig_name=rig_name,
        provider_account_id=provider_account,
        payout_address=payout_address,
        coordinator_url=coordinator_url,
        network_mode=network_mode,
        static_ip=static_ip,
        gateway=gateway,
        dns=dns,
        enable_web_dashboard=enable_web,
        dashboard_port=dash_port,
        allow_ssh=allow_ssh,
        ssh_authorized_keys=ssh_keys,
        disabled_gpus=disabled_gpus,
        vram_reserve_mb=vram_reserve,
        power_mode=power_mode,
        max_temp_c=max_temp,
        enable_kiosk=enable_kiosk,
        auto_update=auto_update,
        auto_system_upgrade=auto_sys_upgrade,
    )


def save_system_config(config: ApplianceConfig, path: Path = DEFAULT_SYSTEM_CONFIG) -> None:
    """Persist updated appliance configuration to disk and USB env partition."""
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(config.to_dict(), indent=2, sort_keys=True) + "\n", encoding="utf-8")
    except Exception:
        pass

    try:
        user_cfg = Path.home() / ".computemesh" / "provider_config.json"
        user_cfg.parent.mkdir(parents=True, exist_ok=True)
        user_data = {}
        if user_cfg.exists():
            try:
                user_data = json.loads(user_cfg.read_text(encoding="utf-8"))
            except Exception:
                pass
        user_data["payout_address"] = config.payout_address
        user_data["rig_name"] = config.rig_name
        user_data["coordinator_url"] = config.coordinator_url
        user_data["power_mode"] = config.power_mode
        user_data["vram_reserve_mb"] = config.vram_reserve_mb
        user_data["max_temp_c"] = config.max_temp_c
        user_data["disabled_gpus"] = config.disabled_gpus
        user_data["updated_at"] = datetime.now(timezone.utc).isoformat() if "datetime" in globals() else ""
        user_cfg.write_text(json.dumps(user_data, indent=2), encoding="utf-8")
    except Exception:
        pass

    # Also update boot computemesh.env if writable
    for env_target in [DEFAULT_BOOT_CONFIG, DEFAULT_LIVE_BOOT_CONFIG]:
        try:
            if env_target.parent.exists() and os.access(env_target.parent, os.W_OK):
                content = f"""# ComputeMesh AI Inference Node Configuration
NODE_NAME={config.rig_name}
WALLET_PAYOUT_ADDRESS={config.payout_address}
PROVIDER_ACCOUNT_ID={config.provider_account_id}
COORDINATOR_URL={config.coordinator_url}
VRAM_RESERVE_MB={config.vram_reserve_mb}
POWER_MODE={config.power_mode}
MAX_TEMP_C={config.max_temp_c}
DISABLED_GPUS={','.join(str(g) for g in config.disabled_gpus)}
ENABLE_WEB_DASHBOARD={'true' if config.enable_web_dashboard else 'false'}
DASHBOARD_PORT={config.dashboard_port}
ENABLE_KIOSK={'true' if config.enable_kiosk else 'false'}
ALLOW_SSH={'true' if config.allow_ssh else 'false'}
"""
                env_target.write_text(content, encoding="utf-8")
        except Exception:
            pass
