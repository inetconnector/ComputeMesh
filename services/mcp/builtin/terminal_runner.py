# SPDX-License-Identifier: Apache-2.0
"""Safe Terminal and Shell Command Execution Tool for ComputeMesh Agentic Coding."""

from __future__ import annotations

import logging
import os
import re
import subprocess
import time
from typing import Any, Dict, Optional

log = logging.getLogger("computemesh.mcp.terminal_runner")

FORBIDDEN_PATTERNS = [
    r"\bformat\s+[a-zA-Z]:",
    r"\brmdir\s+.*[/\-]s",
    r"\bdel\b.*(?:/[sS]|-[rR]|/[qQ]).*[a-zA-Z]:[\\/]",
    r"\bdel\s+.*[a-zA-Z]:[\\/]",
    r"\bdel\s+.*[/\\](?:windows|system32)",
    r"\brm\s+-(?:[a-zA-Z]*r[a-zA-Z]*)\s+(?:/|~|\$HOME)",
    r"\bmkfs\b",
    r"\bdd\s+if=",
    r"\bshutdown\b",
    r"\breboot\b",
]


def run_terminal_command(
    command: str,
    cwd: Optional[str] = None,
    timeout_seconds: float = 35.0,
) -> Dict[str, Any]:
    """Executes a terminal or build command in a controlled workspace subprocess environment."""
    clean_cmd = str(command or "").strip()
    if not clean_cmd:
        return {"error": "Befehl darf nicht leer sein.", "success": False, "exit_code": 1}

    for pat in FORBIDDEN_PATTERNS:
        if re.search(pat, clean_cmd, re.IGNORECASE):
            return {
                "success": False,
                "error": "Sicherheitsrichtlinie blockiert: Destruktive Systembefehle (Formatierung, Root-Löschung, Shutdown) sind gesperrt.",
                "stderr": "Sicherheitsrichtlinie blockiert: Destruktive Systembefehle sind gesperrt.",
                "exit_code": 126,
            }

    work_dir = os.path.abspath(cwd or ".")
    t0 = time.time()

    try:
        proc = subprocess.run(
            clean_cmd,
            cwd=work_dir,
            shell=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=timeout_seconds,
            encoding="utf-8",
            errors="replace",
        )
        elapsed = round(time.time() - t0, 2)
        stdout_txt = proc.stdout or ""
        stderr_txt = proc.stderr or ""

        return {
            "success": proc.returncode == 0,
            "command": clean_cmd,
            "cwd": work_dir.replace("\\", "/"),
            "exit_code": proc.returncode,
            "elapsed_seconds": elapsed,
            "stdout": stdout_txt[:80000] if len(stdout_txt) > 80000 else stdout_txt,
            "stderr": stderr_txt[:80000] if len(stderr_txt) > 80000 else stderr_txt,
        }
    except subprocess.TimeoutExpired:
        return {
            "success": False,
            "command": clean_cmd,
            "error": f"Befehl wurde nach {timeout_seconds}s abgebrochen (Timeout).",
            "exit_code": 124,
        }
    except Exception as exc:
        return {"success": False, "command": clean_cmd, "error": f"Ausführungsfehler: {exc}", "exit_code": 1}
