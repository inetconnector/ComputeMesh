# SPDX-License-Identifier: Apache-2.0
"""Fail-closed Python execution boundary.

In-process exec/eval, shared Python builtins and regex/AST filtering are NOT a
sandbox. This feature remains unavailable until a separately isolated,
resource-limited executor has passed the target-OS security acceptance suite.
Do not accept feature flags or model-supplied parameters to bypass this gate.
"""
from __future__ import annotations

from typing import Any

_DISABLED_MESSAGE = (
    "Python code execution is disabled: no independently approved "
    "isolated executor is installed."
)


def execute_python_code(
    code: str,
    timeout_seconds: float = 15.0,
    store_state: bool = True,
) -> dict[str, Any]:
    """Reject every request without evaluating, importing or running code.

    Preserve the former public return shape and backwards-compatible alias.
    Re-enable only through an independently reviewed, isolated execution
    service with no inherited secrets, default-deny network, OS-level memory/
    CPU/process/time limits and bounded output artifacts.
    """
    del code, timeout_seconds, store_state
    return {
        "status": "disabled",
        "success": False,
        "stdout": "",
        "stderr": "",
        "result": None,
        "error": _DISABLED_MESSAGE,
        "elapsed_seconds": 0.0,
        "images": [],
        "markdown": "Python-Ausführung ist aus Sicherheitsgründen deaktiviert.",
    }


# Existing callers must not fall back to unsafe in-process execution.
run_code_interpreter = execute_python_code
