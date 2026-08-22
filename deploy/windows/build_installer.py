#!/usr/bin/env python3
"""ComputeMesh Windows Standalone Executable & Installer Packaging Engine.

Bundles the lightweight Windows Desktop Provider Agent GUI, hardware discovery modules,
and autostart registry templates into a self-contained installer executable.
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
import shutil
import sys
import zipapp
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]


@dataclass(frozen=True)
class WindowsInstallerPackageResult:
    output_path: Path
    file_size_bytes: int
    sha256_hash: str
    manifest: dict[str, Any]


def build_windows_standalone_bundle(
    output_exe_path: Path,
    version: str = "1.0.0",
) -> WindowsInstallerPackageResult:
    """Builds a standalone executable installer bundle for Windows."""
    output_exe_path = Path(output_exe_path)
    output_exe_path.parent.mkdir(parents=True, exist_ok=True)

    # Staging directory
    staging_dir = output_exe_path.parent / "staging_win_installer"
    if staging_dir.exists():
        shutil.rmtree(staging_dir)
    staging_dir.mkdir(parents=True, exist_ok=True)

    # Copy required provider source files
    tools_dir = staging_dir / "tools" / "appliance"
    tools_dir.mkdir(parents=True, exist_ok=True)
    shutil.copy(REPO_ROOT / "tools" / "appliance" / "hardware_detector.py", tools_dir / "hardware_detector.py")
    shutil.copy(REPO_ROOT / "tools" / "appliance" / "appliance_config.py", tools_dir / "appliance_config.py")
    shutil.copy(REPO_ROOT / "tools" / "appliance" / "windows_tray_app.py", staging_dir / "__main__.py")

    # Create embedded manifest
    manifest = {
        "app_name": "ComputeMesh Provider Agent",
        "version": version,
        "platform": "windows-x64",
        "entrypoint": "__main__.py",
        "author": "ComputeMesh Network Foundation",
        "default_coordinator": "https://computemesh.inetconnector.com",
    }
    (staging_dir / "computemesh_manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")

    # Create zipapp executable bundle
    zipapp.create_archive(
        source=staging_dir,
        target=output_exe_path,
        main=None,  # Uses __main__.py in staging root
        compressed=True,
    )

    shutil.rmtree(staging_dir)

    raw_bytes = output_exe_path.read_bytes()
    sha256 = hashlib.sha256(raw_bytes).hexdigest()

    return WindowsInstallerPackageResult(
        output_path=output_exe_path,
        file_size_bytes=len(raw_bytes),
        sha256_hash=sha256,
        manifest=manifest,
    )
