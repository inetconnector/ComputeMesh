# SPDX-License-Identifier: Apache-2.0
"""Automated Test Runner and Failure Extractor for ComputeMesh Agentic Coding."""

from __future__ import annotations

import logging
import os
import re
import subprocess
import sys
import time
from typing import Any, Dict, List, Optional

log = logging.getLogger("computemesh.mcp.test_runner_tools")


def run_project_tests(
    framework: str = "pytest",
    test_path: str = ".",
    filter_pattern: Optional[str] = None,
    timeout_seconds: float = 45.0,
    cwd: Optional[str] = None,
) -> Dict[str, Any]:
    """Executes automated test suites (pytest, go test, npm, cargo) and parses structured test results."""
    clean_framework = str(framework or "pytest").lower().strip()
    work_dir = os.path.abspath(cwd or ".")

    if clean_framework == "pytest":
        cmd = [sys.executable, "-m", "pytest", "-v", test_path]
        if filter_pattern:
            cmd.extend(["-k", filter_pattern])
    elif clean_framework in ("go", "gotest", "go_test"):
        cmd = ["go", "test", "-v", test_path]
        if filter_pattern:
            cmd.extend(["-run", filter_pattern])
    elif clean_framework in ("npm", "node", "jest"):
        cmd = ["npm", "test"]
    elif clean_framework in ("cargo", "rust"):
        cmd = ["cargo", "test"]
    else:
        return {"error": f"Nicht unterstütztes Test-Framework: '{framework}'. Unterstützt: pytest, go, npm, cargo.", "success": False}

    t0 = time.time()
    try:
        proc = subprocess.run(
            cmd,
            cwd=work_dir,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=timeout_seconds,
            encoding="utf-8",
            errors="replace",
        )
        elapsed = round(time.time() - t0, 2)
        raw_out = (proc.stdout or "") + "\n" + (proc.stderr or "")

        # Extract structured test counts
        passed = 0
        failed = 0
        errors = 0
        failures: List[Dict[str, str]] = []

        if clean_framework == "pytest":
            # Regex for "X passed, Y failed"
            m_pass = re.search(r"(\d+)\s+passed", raw_out)
            m_fail = re.search(r"(\d+)\s+failed", raw_out)
            m_err = re.search(r"(\d+)\s+error", raw_out)
            passed = int(m_pass.group(1)) if m_pass else (1 if proc.returncode == 0 else 0)
            failed = int(m_fail.group(1)) if m_fail else (1 if proc.returncode != 0 else 0)
            errors = int(m_err.group(1)) if m_err else 0

            # Extract FAILED line items
            for line in raw_out.splitlines():
                if line.startswith("FAILED "):
                    parts = line.split(" - ")
                    failures.append({
                        "test": parts[0].replace("FAILED ", "").strip(),
                        "message": parts[1].strip() if len(parts) > 1 else "",
                    })

        elif clean_framework in ("go", "gotest"):
            passed = len(re.findall(r"^--- PASS:", raw_out, re.MULTILINE))
            failed = len(re.findall(r"^--- FAIL:", raw_out, re.MULTILINE))
            for m in re.finditer(r"^--- FAIL:\s+([A-Za-z0-9_]+)", raw_out, re.MULTILINE):
                failures.append({"test": m.group(1), "message": "Go Test Assertion Failed"})

        is_success = (proc.returncode == 0) and (failed == 0) and (errors == 0)
        return {
            "success": is_success,
            "framework": clean_framework,
            "exit_code": proc.returncode,
            "passed": passed,
            "failed": failed,
            "errors": errors,
            "total": passed + failed + errors,
            "elapsed_seconds": elapsed,
            "failures": failures,
            "summary": f"{passed} bestanden, {failed} fehlgeschlagen ({elapsed}s)",
            "output_preview": raw_out[-2500:] if len(raw_out) > 2500 else raw_out,
        }
    except subprocess.TimeoutExpired:
        return {
            "success": False,
            "framework": clean_framework,
            "error": f"Test-Ausführung nach {timeout_seconds}s abgebrochen (Timeout).",
            "passed": 0,
            "failed": 1,
            "failures": [{"test": "timeout", "message": f"Execution exceeded {timeout_seconds}s"}],
        }
    except Exception as exc:
        return {"success": False, "framework": clean_framework, "error": f"Test-Runner Fehler: {exc}"}
