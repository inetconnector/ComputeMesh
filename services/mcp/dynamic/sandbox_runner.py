# SPDX-License-Identifier: Apache-2.0
"""
Isolated Subprocess Sandbox Runner for Dynamic Python Tools.
Enforces CPU time limits, RAM limits (256MB), wall-clock timeouts,
and clean JSON IPC over standard streams.
"""

from __future__ import annotations

import json
import os
import sys
import subprocess
import time
from typing import Any, Dict, Optional, Tuple

MAX_OUTPUT_PAYLOAD_BYTES = 64 * 1024  # 64 KB
DEFAULT_TIMEOUT_SECONDS = 3.0
MAX_MEMORY_BYTES = 256 * 1024 * 1024  # 256 MB


class SandboxExecutionError(Exception):
    """Raised when sandbox execution crashes or returns an error."""
    pass


class SandboxTimeoutError(Exception):
    """Raised when sandbox execution exceeds wall-clock or CPU quotas."""
    pass


# Micro-runner script executed inside the isolated child process
_CHILD_RUNNER_TEMPLATE = '''# -*- coding: utf-8 -*-
import sys
import json
import traceback

# Restrict resources on Linux/POSIX if available
try:
    import resource
    # 2s CPU soft limit, 3s hard limit
    resource.setrlimit(resource.RLIMIT_CPU, (2, 3))
    # 256 MB address space limit
    resource.setrlimit(resource.RLIMIT_AS, (256 * 1024 * 1024, 256 * 1024 * 1024))
    # Prevent creating child processes (fork bomb defense)
    if hasattr(resource, 'RLIMIT_NPROC'):
        resource.setrlimit(resource.RLIMIT_NPROC, (1, 1))
except Exception:
    pass

# Dynamically executed tool code
{USER_CODE}

if __name__ == '__main__':
    try:
        raw_input = sys.stdin.read()
        inputs = json.loads(raw_input) if raw_input.strip() else {{}}
        if not isinstance(inputs, dict):
            inputs = {{"data": inputs}}
        
        result = execute(inputs)
        
        # Ensure result is serializable dict
        if not isinstance(result, dict):
            result = {{"result": result}}
            
        output_json = json.dumps(result, ensure_ascii=False)
        sys.stdout.write(output_json)
        sys.stdout.flush()
        sys.exit(0)
    except Exception as exc:
        err_payload = {{
            "error": str(exc),
            "error_type": exc.__class__.__name__,
            "traceback": traceback.format_exc()
        }}
        sys.stderr.write(json.dumps(err_payload, ensure_ascii=False))
        sys.stderr.flush()
        sys.exit(1)
'''


def run_code_in_sandbox(
    code: str,
    inputs: Dict[str, Any],
    timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
) -> Dict[str, Any]:
    """
    Executes Python tool code within an isolated child process with hardware quotas.
    Returns the execution output dictionary.
    """
    child_script = _CHILD_RUNNER_TEMPLATE.format(USER_CODE=code)
    input_payload = json.dumps(inputs, ensure_ascii=False)

    start_time = time.perf_counter()

    try:
        proc = subprocess.Popen(
            [sys.executable, "-c", child_script],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
        )

        stdout_data, stderr_data = proc.communicate(
            input=input_payload,
            timeout=timeout_seconds,
        )
    except subprocess.TimeoutExpired:
        try:
            proc.kill()
            proc.communicate()
        except Exception:
            pass
        elapsed = round(time.perf_counter() - start_time, 3)
        raise SandboxTimeoutError(
            f"Ausführungszeit hat das Sicherheitslimit von {timeout_seconds}s überschritten ({elapsed}s)."
        )

    elapsed = round(time.perf_counter() - start_time, 3)

    if proc.returncode != 0:
        err_msg = stderr_data.strip()
        try:
            parsed_err = json.loads(err_msg)
            err_text = parsed_err.get("error", err_msg)
            err_type = parsed_err.get("error_type", "ExecutionError")
            raise SandboxExecutionError(f"{err_type}: {err_text}")
        except json.JSONDecodeError:
            raise SandboxExecutionError(f"Prozess beendet mit Fehlercode {proc.returncode}: {err_msg}")

    # Parse and validate output JSON
    output_raw = stdout_data.strip()
    if not output_raw:
        return {"result": None, "elapsed_seconds": elapsed}

    if len(output_raw.encode("utf-8")) > MAX_OUTPUT_PAYLOAD_BYTES:
        raise SandboxExecutionError(
            f"Ergebnis-Payload ({len(output_raw.encode('utf-8'))} Bytes) übersteigt das Maximum von {MAX_OUTPUT_PAYLOAD_BYTES} Bytes."
        )

    try:
        res = json.loads(output_raw)
        if isinstance(res, dict):
            res["_sandbox_metrics"] = {
                "elapsed_seconds": elapsed,
                "exit_code": 0,
            }
            return res
        return {"result": res, "_sandbox_metrics": {"elapsed_seconds": elapsed, "exit_code": 0}}
    except json.JSONDecodeError as exc:
        raise SandboxExecutionError(f"Ungültige JSON-Ausgabe aus Sandbox: {exc.msg}")
