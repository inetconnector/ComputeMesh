# SPDX-License-Identifier: Apache-2.0
"""Android Edge Node and Device ADB Bridge Tool for ComputeMesh."""

from __future__ import annotations

import base64
import logging
import os
import shutil
import subprocess
import time
from typing import Any

log = logging.getLogger("computemesh.mcp.adb_bridge")


def _find_adb_binary() -> str:
    loc = shutil.which("adb")
    if loc:
        return loc
    # Fallback to standard SDK locations
    candidates = [
        os.path.expandvars(r"%LOCALAPPDATA%\Android\Sdk\platform-tools\adb.exe"),
        os.path.expandvars(r"%ANDROID_HOME%\platform-tools\adb.exe"),
        os.path.expandvars(r"%ANDROID_SDK_ROOT%\platform-tools\adb.exe"),
        os.path.expanduser("~/Android/Sdk/platform-tools/adb"),
        os.path.expanduser("~/Library/Android/sdk/platform-tools/adb"),
    ]
    for c in candidates:
        if os.path.exists(c):
            return c
    return "adb"


def _resolve_device_arg(device_id: str | None = None) -> list[str]:
    return ["-s", device_id.strip()] if device_id and device_id.strip() else []


def adb_list_devices() -> dict[str, Any]:
    """Lists all connected Android physical devices and emulators with models."""
    try:
        adb_bin = _find_adb_binary()
        proc = subprocess.run(
            [adb_bin, "devices", "-l"],
            check=False, capture_output=True,
            text=True,
            timeout=8.0,
            shell=True,
        )
        if proc.returncode != 0:
            return {"error": f"ADB-Befehl fehlgeschlagen: {proc.stderr}", "devices": []}

        lines = proc.stdout.strip().splitlines()
        devices: list[dict[str, Any]] = []

        for line in lines[1:]:
            parts = line.strip().split()
            if len(parts) >= 2 and parts[1] == "device":
                d_id = parts[0]
                model = "Android Device"
                for p in parts[2:]:
                    if p.startswith("model:"):
                        model = p.split(":", 1)[1].replace("_", " ")
                devices.append({
                    "device_id": d_id,
                    "status": "online",
                    "model": model,
                    "is_emulator": "emulator" in d_id,
                })

        return {
            "success": True,
            "total_devices": len(devices),
            "devices": devices,
        }
    except Exception as exc:
        return {"success": False, "error": f"ADB nicht verfügbar: {exc}", "devices": []}


def adb_capture_screenshot(
    device_id: str | None = None,
    output_path: str | None = None,
) -> dict[str, Any]:
    """Captures a real-time PNG screenshot from a connected Android edge device."""
    adb_bin = _find_adb_binary()
    args = [adb_bin] + _resolve_device_arg(device_id) + ["exec-out", "screencap", "-p"]
    t0 = time.time()
    try:
        proc = subprocess.run(args, check=False, capture_output=True, timeout=12.0, shell=True)
        if proc.returncode != 0 or not proc.stdout:
            return {"error": "Screenshot-Aufnahme fehlgeschlagen.", "success": False}

        raw_png = proc.stdout
        out_target = output_path or os.path.join(os.getcwd(), f"adb_screen_{int(time.time())}.png")
        with open(out_target, "wb") as f:
            f.write(raw_png)

        b64_preview = base64.b64encode(raw_png[:64000]).decode("ascii")
        elapsed = round(time.time() - t0, 2)
        return {
            "success": True,
            "saved_path": out_target.replace("\\", "/"),
            "bytes_size": len(raw_png),
            "elapsed_seconds": elapsed,
            "device_id": device_id or "default",
            "base64_preview": b64_preview,
        }
    except Exception as exc:
        return {"success": False, "error": f"Screenshot-Fehler: {exc}"}


def adb_install_app(apk_path: str, device_id: str | None = None) -> dict[str, Any]:
    """Installs or updates an Android APK on a target connected device."""
    if not os.path.exists(apk_path):
        return {"error": f"APK-Datei '{apk_path}' nicht gefunden.", "success": False}

    adb_bin = _find_adb_binary()
    args = [adb_bin] + _resolve_device_arg(device_id) + ["install", "-r", apk_path]
    try:
        proc = subprocess.run(args, check=False, capture_output=True, text=True, timeout=60.0, shell=True)
        out = (proc.stdout or "") + (proc.stderr or "")
        success = "Success" in out
        return {
            "success": success,
            "apk_path": apk_path,
            "device_id": device_id or "default",
            "output": out.strip(),
        }
    except Exception as exc:
        return {"success": False, "error": f"Installationsfehler: {exc}"}


def adb_get_system_log(
    device_id: str | None = None,
    lines: int = 50,
    filter_tag: str | None = None,
) -> dict[str, Any]:
    """Fetches recent logcat entries from the Android edge node."""
    adb_bin = _find_adb_binary()
    args = [adb_bin] + _resolve_device_arg(device_id) + ["logcat", "-d", "-t", str(min(200, lines))]
    try:
        proc = subprocess.run(args, check=False, capture_output=True, text=True, timeout=10.0, shell=True)
        raw_log = proc.stdout or ""
        log_lines = raw_log.splitlines()
        if filter_tag:
            log_lines = [line for line in log_lines if filter_tag.lower() in line.lower()]

        return {
            "success": True,
            "device_id": device_id or "default",
            "total_lines": len(log_lines),
            "log": "\n".join(log_lines[-lines:]),
        }
    except Exception as exc:
        return {"success": False, "error": f"Logcat-Fehler: {exc}"}
