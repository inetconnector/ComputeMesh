#!/usr/bin/env python3
"""ComputeMesh Appliance Configuration Loader.

Parses node configuration from the FAT32 boot partition (/boot/computemesh.env),
local system configuration (/etc/computemesh/config.json), or environment variables.
"""
from __future__ import annotations

import argparse
from dataclasses import asdict, dataclass
import json
import os
from pathlib import Path
import re
import sys
from typing import Any

DEFAULT_BOOT_CONFIG = Path("/boot/computemesh.env")
DEFAULT_SYSTEM_CONFIG = Path("/etc/computemesh/config.json")


@dataclass(frozen=True)
class ApplianceConfig:
    rig_name: str
    provider_account_id: str
    coordinator_url: str
    network_mode: str  # "dhcp" or "static"
    static_ip: str | None
    gateway: str | None
    dns: str | None
    enable_web_dashboard: bool
    dashboard_port: int
    allow_ssh: bool
    ssh_authorized_keys: str | None

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
    
    system_data: dict[str, Any] = {}
    if system_path.exists():
        try:
            system_data = json.loads(system_path.read_text(encoding="utf-8"))
        except Exception:
            pass

    rig_name = env_vars.get("RIG_NAME") or system_data.get("rig_name") or os.environ.get("RIG_NAME") or "cm-miner-rig-01"
    provider_account = (
        env_vars.get("PROVIDER_ACCOUNT_ID")
        or system_data.get("provider_account_id")
        or os.environ.get("PROVIDER_ACCOUNT_ID")
        or "cm_provider_anonymous"
    )
    coordinator_url = (
        env_vars.get("COORDINATOR_URL")
        or system_data.get("coordinator_url")
        or os.environ.get("COORDINATOR_URL")
        or "https://coordinator.computemesh.net"
    )
    network_mode = env_vars.get("NETWORK_MODE") or system_data.get("network_mode") or "dhcp"
    static_ip = env_vars.get("STATIC_IP") or system_data.get("static_ip")
    gateway = env_vars.get("GATEWAY") or system_data.get("gateway")
    dns = env_vars.get("DNS") or system_data.get("dns")
    
    enable_web = env_vars.get("ENABLE_WEB_DASHBOARD", "true").lower() in ("true", "1", "yes")
    dash_port = int(env_vars.get("DASHBOARD_PORT") or system_data.get("dashboard_port") or 8080)
    allow_ssh = env_vars.get("ALLOW_SSH", "true").lower() in ("true", "1", "yes")
    ssh_keys = env_vars.get("SSH_AUTHORIZED_KEYS") or system_data.get("ssh_authorized_keys")

    return ApplianceConfig(
        rig_name=rig_name,
        provider_account_id=provider_account,
        coordinator_url=coordinator_url,
        network_mode=network_mode,
        static_ip=static_ip,
        gateway=gateway,
        dns=dns,
        enable_web_dashboard=enable_web,
        dashboard_port=dash_port,
        allow_ssh=allow_ssh,
        ssh_authorized_keys=ssh_keys,
    )


def save_system_config(config: ApplianceConfig, path: Path = DEFAULT_SYSTEM_CONFIG) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(config.to_dict(), indent=2, sort_keys=True) + "\n", encoding="utf-8")
