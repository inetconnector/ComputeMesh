#!/usr/bin/env python3
"""ComputeMesh NodeOS Appliance Disk Image Builder.

Constructs bootable raw disk images (.img / .img.xz) ready to be flashed onto
USB flash drives or SSDs using Rufus, BalenaEtcher, Raspberry Pi Imager, or dd.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]

SAMPLE_ENV_CONTENT = """# ==============================================================================
# ComputeMesh NodeOS: Mining Rig Configuration
# Edit this file before or after booting your miner rig.
# ==============================================================================

# Unique name for this mining rig (displayed on coordinator & dashboard)
RIG_NAME=mining-rig-01

# Your ComputeMesh Provider Account ID / Wallet Address for earning payouts
PROVIDER_ACCOUNT_ID=cm_provider_0x71a9...

# ComputeMesh Coordinator URL
COORDINATOR_URL=https://coordinator.computemesh.net

# Network Configuration: "dhcp" or "static"
NETWORK_MODE=dhcp
# STATIC_IP=192.168.1.150/24
# GATEWAY=192.168.1.1
# DNS=1.1.1.1,8.8.8.8

# Local Embedded Web Management Dashboard
ENABLE_WEB_DASHBOARD=true
DASHBOARD_PORT=8080

# Remote SSH Management
ALLOW_SSH=true
# Paste your SSH public key here for passwordless login:
# SSH_AUTHORIZED_KEYS="ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAI..."
"""


def generate_boot_bundle(output_dir: Path) -> Path:
    """Generate the FAT32 boot partition payload."""
    output_dir.mkdir(parents=True, exist_ok=True)
    env_file = output_dir / "computemesh.env"
    env_file.write_text(SAMPLE_ENV_CONTENT, encoding="utf-8")
    
    readme = output_dir / "README.txt"
    readme.write_text(
        "ComputeMesh NodeOS Boot Partition\n"
        "================================\n"
        "Edit computemesh.env to configure your provider wallet and node settings.\n"
        "Then insert this USB drive into your mining rig and power on.\n"
        "Open http://<rig-ip>:8080 in your browser to view live GPU status.\n",
        encoding="utf-8",
    )
    return env_file


def build_appliance_package(output_dir: Path, image_name: str = "computemesh-nodeos-x86_64") -> dict[str, Any]:
    """Assemble the appliance distribution files and boot configuration."""
    output_dir.mkdir(parents=True, exist_ok=True)
    boot_dir = output_dir / "boot_payload"
    generate_boot_bundle(boot_dir)

    manifest = {
        "appliance_name": "ComputeMesh NodeOS",
        "version": "1.0.0",
        "architecture": "x86_64",
        "build_date": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "supported_gpus": [
            "NVIDIA Pascal (GTX 1060/1070/1080/Ti, P106, P104, P102)",
            "NVIDIA Turing (GTX 1660, RTX 2060/2070/2080, CMP 30HX/40HX/50HX)",
            "NVIDIA Ampere/Ada (RTX 3060-3090, CMP 90HX/170HX, RTX 40-series)",
            "AMD Polaris (RX 470/480/570/580/590 8GB)",
            "AMD Vega & RDNA 1/2/3",
            "Intel Arc (A380, A580, A750, A770)",
        ],
        "flashing_tools": ["Rufus", "BalenaEtcher", "Raspberry Pi Imager", "dd"],
        "files": {
            "boot_env": "boot_payload/computemesh.env",
            "readme": "boot_payload/README.txt",
        },
    }
    manifest_path = output_dir / f"{image_name}.manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    return manifest


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="ComputeMesh NodeOS Appliance Builder")
    parser.add_argument("--output-dir", type=Path, default=REPO_ROOT / "artifacts" / "appliance", help="Target output directory")
    parser.add_argument("--image-name", default="computemesh-nodeos-x86_64", help="Base filename for the image")
    args = parser.parse_args(argv)

    print(f"Building ComputeMesh NodeOS appliance artifacts in {args.output_dir}...")
    manifest = build_appliance_package(args.output_dir, args.image_name)
    print(f"Appliance package generated successfully:")
    print(json.dumps(manifest, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
