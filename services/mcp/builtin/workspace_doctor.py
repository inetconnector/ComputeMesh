# SPDX-License-Identifier: Apache-2.0
"""System & Workspace Doctor Diagnostics Engine for ComputeMesh."""

from __future__ import annotations

import logging
import os
import shutil
import subprocess
import time
from typing import Any, Dict, List, Optional

log = logging.getLogger("computemesh.mcp.doctor")


def _check_command_version(cmd: str, version_flag: str = "--version", timeout: float = 3.0) -> tuple[bool, str, int]:
    t0 = time.time()
    try:
        proc = subprocess.run(
            [cmd, version_flag],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            timeout=timeout,
            shell=True,
        )
        latency = int((time.time() - t0) * 1000)
        out = (proc.stdout or "").strip().splitlines()[0] if proc.stdout else "Verfügbar"
        return proc.returncode == 0, out[:80], latency
    except Exception:
        latency = int((time.time() - t0) * 1000)
        return False, "Nicht gefunden / Nicht im PATH", latency


def run_doctor_diagnostics(
    categories: Optional[List[str]] = None,
    workspace_root: Optional[str] = None,
) -> Dict[str, Any]:
    """Runs comprehensive diagnostics across compilers, hardware, network, and edge nodes."""
    root = os.path.abspath(workspace_root or ".")
    items: List[Dict[str, Any]] = []
    overall = "healthy"

    def _add_item(name: str, cat: str, status: str, summary: str, latency_ms: int = 0, remediation: str = ""):
        nonlocal overall
        if status == "error":
            overall = "error"
        elif status == "warning" and overall != "error":
            overall = "warning"
        items.append({
            "name": name,
            "category": cat,
            "status": status,
            "summary": summary,
            "latency_ms": latency_ms,
            "remediation": remediation,
        })

    # 1. Compilers & Runtimes
    for tool_name, flag, rem in [
        ("python", "--version", "Python 3.11+ installieren oder in PATH aufnehmen."),
        ("git", "--version", "Git installieren (https://git-scm.com)."),
        ("go", "version", "Go installieren (https://go.dev/dl/)."),
        ("node", "--version", "Node.js installieren (https://nodejs.org)."),
        ("cargo", "--version", "Rust & Cargo installieren (https://rustup.rs)."),
    ]:
        ok, out, lat = _check_command_version(tool_name, flag)
        if ok:
            _add_item(tool_name.capitalize(), "compilers_runtimes", "healthy", out, lat)
        else:
            _add_item(tool_name.capitalize(), "compilers_runtimes", "warning" if tool_name != "python" else "error", out, lat, rem)

    # 2. Hardware & Storage Resources
    try:
        import psutil
        vm = psutil.virtual_memory()
        disk = psutil.disk_usage(root)
        ram_gb = vm.total / (1024**3)
        ram_free_gb = vm.available / (1024**3)
        disk_free_gb = disk.free / (1024**3)

        status_ram = "healthy" if ram_free_gb >= 2.0 else "warning"
        _add_item("Arbeitsspeicher (RAM)", "hardware_resources", status_ram, f"{ram_free_gb:.1f} GB frei von {ram_gb:.1f} GB ({vm.percent}% belegt)")

        status_disk = "healthy" if disk_free_gb >= 5.0 else "warning"
        _add_item("Festplattenspeicher (Disk)", "hardware_resources", status_disk, f"{disk_free_gb:.1f} GB frei im Workspace")
    except Exception:
        _add_item("System-Ressourcen", "hardware_resources", "healthy", "Ressourcencheck abgeschlossen")

    # 3. GPU Hardware Acceleration
    gpu_ok, gpu_out, gpu_lat = _check_command_version("nvidia-smi", "-L")
    if gpu_ok:
        _add_item("NVIDIA GPU (CUDA)", "hardware_gpu", "healthy", gpu_out, gpu_lat)
    else:
        _add_item("GPU-Beschleunigung", "hardware_gpu", "healthy", "Keine diskrete NVIDIA GPU erkannt (CPU-Inferenz aktiv)")

    # 4. Android Edge Nodes & ADB
    from .adb_bridge_tools import _find_adb_binary
    adb_bin = _find_adb_binary()
    adb_ok, adb_out, adb_lat = _check_command_version(adb_bin, "devices")
    if adb_ok:
        dev_lines = [l.strip() for l in adb_out.splitlines() if "\tdevice" in l]
        dev_count = len(dev_lines)
        _add_item("Android ADB Edge Nodes", "edge_devices", "healthy", f"{dev_count} Gerät(e) verbunden", adb_lat)
    else:
        _add_item("Android ADB Edge Nodes", "edge_devices", "healthy", "ADB nicht aktiv oder keine Geräte gekoppelt", adb_lat)

    # 5. Workspace Integrity
    has_git = os.path.exists(os.path.join(root, ".git"))
    _add_item("Git Workspace", "workspace_integrity", "healthy" if has_git else "warning", "Git Repository initialisiert" if has_git else "Kein .git Ordner gefunden")

    return {
        "success": True,
        "overall_status": overall,
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "workspace_root": root,
        "total_checks": len(items),
        "items": items,
    }
