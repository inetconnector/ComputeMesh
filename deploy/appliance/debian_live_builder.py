#!/usr/bin/env python3
"""ComputeMesh Debian Live NodeOS Image Builder (Appliance Distribution).

Automates the generation of minimal, turnkey, bootable USB appliance images (.img.xz / .iso)
pre-packaged with AMD (Mesa RADV/ROCm) and NVIDIA (CUDA/SMI) dual-stack drivers,
automatic FAT32 configuration auto-mounting, and the autonomous provider inference daemon.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import shutil
import sys
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]


@dataclass(frozen=True)
class ApplianceBuildConfig:
    distribution: str = "trixie"  # Debian 13 (Trixie) base
    architecture: str = "amd64"
    image_name: str = "computemesh-nodeos-x86_64"
    kernel_flavor: str = "amd64"
    enable_nonfree_firmware: bool = True


REQUIRED_PACKAGES = [
    "linux-image-amd64",
    "live-boot",
    "systemd-sysv",
    "firmware-linux",
    "firmware-amd-graphics",
    "firmware-misc-nonfree",
    "mesa-vulkan-drivers",
    "vulkan-tools",
    "libvulkan1",
    "pciutils",
    "usbutils",
    "lm-sensors",
    "ethtool",
    "curl",
    "wget",
    "python3",
    "python3-venv",
    "python3-pip",
    "sudo",
]


class DebianLiveBuilder:
    def __init__(self, build_dir: Path, config: ApplianceBuildConfig | None = None) -> None:
        self.build_dir = Path(build_dir)
        self.config = config or ApplianceBuildConfig()

    def generate_build_manifest(self) -> dict[str, Any]:
        """Assembles the complete live-build configuration manifest."""
        manifest = {
            "distribution": self.config.distribution,
            "architecture": self.config.architecture,
            "image_type": "hdd",
            "binary_format": "img.xz",
            "archive_areas": "main contrib non-free non-free-firmware",
            "boot_append": "boot=live components quiet splash persistence computemesh.autostart=1",
            "packages": REQUIRED_PACKAGES,
            "systemd_services": [
                "computemesh-appliance.service",
                "computemesh-dashboard.service",
            ],
            "auto_mount_env": "/boot/computemesh.env",
        }
        return manifest

    def create_build_tree(self) -> Path:
        """Sets up the live-build directory tree and bootstrap configurations."""
        self.build_dir.mkdir(parents=True, exist_ok=True)
        config_dir = self.build_dir / "config"
        config_dir.mkdir(exist_ok=True)

        # 1. Package list
        pkg_file = config_dir / "package-lists" / "computemesh.list.chroot"
        pkg_file.parent.mkdir(parents=True, exist_ok=True)
        pkg_file.write_text("\n".join(REQUIRED_PACKAGES) + "\n", encoding="utf-8")

        # 2. Systemd autostart unit
        service_file = config_dir / "includes.chroot" / "etc" / "systemd" / "system" / "computemesh-appliance.service"
        service_file.parent.mkdir(parents=True, exist_ok=True)
        service_file.write_text(
            """[Unit]
Description=ComputeMesh Autonomous Provider Appliance Daemon
After=network.target

[Service]
ExecStart=/opt/computemesh/bin/computemesh-node --boot-config /boot/computemesh.env
Restart=always
RestartSec=5
User=root

[Install]
WantedBy=multi-user.target
""",
            encoding="utf-8",
        )

        # 3. FAT32 default configuration template
        env_file = config_dir / "includes.binary" / "computemesh.env"
        env_file.parent.mkdir(parents=True, exist_ok=True)
        env_file.write_text(
            """# ComputeMesh NodeOS USB Boot Configuration
NODE_NAME=mining-rig-01
WALLET_PAYOUT_ADDRESS=0x0000000000000000000000000000000000000000
API_KEY=cm_node_default_key
COORDINATOR_URL=https://computemesh.inetconnector.com
AUTO_UPDATE=true
VRAM_RESERVE_MB=512
ENABLE_DASHBOARD=true
DASHBOARD_PORT=8080
""",
            encoding="utf-8",
        )

        return self.build_dir
