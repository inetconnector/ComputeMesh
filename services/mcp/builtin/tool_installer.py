# SPDX-License-Identifier: Apache-2.0
"""Developer Tool and Package Auto-Installer Engine for ComputeMesh."""

from __future__ import annotations

import logging
import os
import shutil
import subprocess
import sys
import time
from typing import Any, Dict, List, Optional

log = logging.getLogger("computemesh.mcp.tool_installer")

KNOWN_TOOLS = {
    "pytest": {"manager": "pip", "pkg": "pytest"},
    "ruff": {"manager": "pip", "pkg": "ruff"},
    "flake8": {"manager": "pip", "pkg": "flake8"},
    "mypy": {"manager": "pip", "pkg": "mypy"},
    "black": {"manager": "pip", "pkg": "black"},
    "isort": {"manager": "pip", "pkg": "isort"},
    "ripgrep": {"manager": "winget", "pkg": "BurntSushi.ripgrep.MSVC", "linux_pkg": "ripgrep"},
    "ffmpeg": {"manager": "winget", "pkg": "Gyan.FFmpeg", "linux_pkg": "ffmpeg"},
    "jq": {"manager": "winget", "pkg": "jqlang.jq", "linux_pkg": "jq"},
}


def detect_missing_tools(tool_names: Optional[List[str]] = None) -> Dict[str, Any]:
    """Scans system PATH to identify installed vs missing development tools."""
    targets = tool_names or list(KNOWN_TOOLS.keys())
    installed = []
    missing = []

    for name in targets:
        clean_name = name.strip()
        loc = shutil.which(clean_name)
        if not loc and clean_name.lower() in ("python", "python3"):
            loc = sys.executable
        if not loc:
            for ext in (".exe", ".cmd", ".bat", ".ps1"):
                found = shutil.which(clean_name + ext)
                if found:
                    loc = found
                    break

        if loc:
            installed.append({"name": clean_name, "path": loc.replace("\\", "/")})
        else:
            rec = KNOWN_TOOLS.get(clean_name, {})
            mgr = rec.get("manager", "pip")
            pkg = rec.get("pkg", clean_name)
            cmd = f"{mgr} install {pkg}" if mgr == "pip" else f"winget install {pkg}"
            missing.append({
                "name": clean_name,
                "recommended_manager": mgr,
                "install_command": cmd,
            })

    return {
        "success": True,
        "total_scanned": len(targets),
        "installed_count": len(installed),
        "missing_count": len(missing),
        "installed": installed,
        "missing": missing,
    }


def install_dev_tool(tool_name: str, package_manager: Optional[str] = None) -> Dict[str, Any]:
    """Installs a requested Python or CLI developer tool safely."""
    clean_name = str(tool_name or "").strip().lower()
    rec = KNOWN_TOOLS.get(clean_name, {})
    mgr = package_manager or rec.get("manager", "pip")
    pkg = rec.get("pkg", clean_name)

    if mgr == "pip":
        cmd = [sys.executable, "-m", "pip", "install", pkg]
    elif mgr == "npm":
        cmd = ["npm", "install", "-g", pkg]
    else:
        return {"error": f"Automatisierte Installation via '{mgr}' erfordert manuelle Ausführung: 'winget install {pkg}'", "success": False}

    t0 = time.time()
    try:
        proc = subprocess.run(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=60.0,
            shell=True,
        )
        elapsed = round(time.time() - t0, 2)
        return {
            "success": proc.returncode == 0,
            "tool_name": clean_name,
            "manager": mgr,
            "elapsed_seconds": elapsed,
            "stdout": proc.stdout[:2000] if proc.stdout else "",
            "stderr": proc.stderr[:2000] if proc.stderr else "",
        }
    except Exception as exc:
        return {"success": False, "tool_name": clean_name, "error": f"Installationsfehler: {exc}"}
