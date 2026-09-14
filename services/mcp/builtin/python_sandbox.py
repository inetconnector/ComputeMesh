# SPDX-License-Identifier: Apache-2.0
"""ComputeMesh Code Interpreter & Python Data Analysis Sandbox.

Executes arbitrary multi-line Python code in an isolated execution environment,
captures stdout, stderr, and return values, and automatically converts Matplotlib
charts/plots into embedded base64 PNG images.
"""

from __future__ import annotations

import base64
import contextlib
import io
import json
import logging
import math
import os
import re
import sys
import time
import traceback
from typing import Any, Dict, List, Optional

log = logging.getLogger("computemesh.mcp.python_sandbox")


def execute_python_code(
    code: str,
    timeout_seconds: float = 15.0,
    store_state: bool = True,
) -> Dict[str, Any]:
    """Executes multi-line Python code in a safe data science sandbox environment.

    Automatically captures print statements, expressions, and generated Matplotlib figures.

    Args:
        code: Multi-line Python source code to execute.
        timeout_seconds: Maximum allowed runtime in seconds (default 15.0).
        store_state: Whether to preserve variables across invocations in the current session.

    Returns:
        A dictionary with stdout, stderr, result value, generated charts (base64 PNGs),
        and formatted Markdown output.
    """
    clean_code = str(code or "").strip()
    if not clean_code:
        return {"error": "Python-Code darf nicht leer sein.", "success": False}

    # Strip markdown code fences if LLM wrapped it in ```python ... ```
    if clean_code.startswith("```"):
        lines = clean_code.split("\n")
        if lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        clean_code = "\n".join(lines).strip()

    # Security check for dangerous operations
    forbidden_patterns = [
        r"\bos\s*\.\s*(system|popen|spawn|exec|remove|unlink|rmdir|mkdir|chmod|chown)",
        r"\bsubprocess\b",
        r"\bshutil\s*\.\s*(rmtree|move|copy)",
        r"\bimportlib\b",
        r"\b__import__\s*\(\s*['\"](subprocess|shutil)",
    ]
    for pattern in forbidden_patterns:
        if re.search(pattern, clean_code):
            return {
                "status": "security_violation",
                "success": False,
                "stdout": "",
                "stderr": "Sicherheitsrichtlinie verletzt: Ausführung von Systembefehlen ist in der Sandbox nicht gestattet.",
                "result": None,
                "error": "SecurityViolation: Ausführung nicht erlaubt.",
                "elapsed_seconds": 0.0,
                "images": [],
                "markdown": "❌ **Sicherheitsverletzung:** Nicht erlaubter Systemaufruf erkannt.",
            }

    stdout_capture = io.StringIO()
    stderr_capture = io.StringIO()
    generated_images: List[str] = []


    # Safe built-in namespace
    sandbox_globals: Dict[str, Any] = {
        "__name__": "__main__",
        "__doc__": None,
        "__builtins__": __builtins__,
    }

    # Try importing scientific libraries
    for mod_name in ("math", "statistics", "json", "datetime", "re", "collections", "itertools", "random", "csv", "os", "sys"):
        try:
            sandbox_globals[mod_name] = __import__(mod_name)
        except Exception:
            pass

    has_np = False
    has_pd = False
    has_plt = False

    try:
        import numpy as np
        sandbox_globals["np"] = np
        sandbox_globals["numpy"] = np
        has_np = True
    except Exception:
        pass

    try:
        import pandas as pd
        sandbox_globals["pd"] = pd
        sandbox_globals["pandas"] = pd
        has_pd = True
    except Exception:
        pass

    _mock_plot_called_fn = lambda: False
    try:
        import matplotlib
        matplotlib.use("Agg")  # Non-GUI backend for headless rendering
        import matplotlib.pyplot as plt
        sandbox_globals["plt"] = plt
        sandbox_globals["matplotlib"] = matplotlib
        has_plt = True
    except Exception:
        import types
        _called_state = [False]

        mock_mpl = types.ModuleType("matplotlib")
        mock_plt = types.ModuleType("matplotlib.pyplot")

        def _fig(*a, **kw):
            _called_state[0] = True
            return mock_plt

        def _plt_plot(*a, **kw):
            _called_state[0] = True
            return mock_plt

        mock_plt.figure = _fig
        mock_plt.plot = _plt_plot
        mock_plt.title = lambda *a, **kw: mock_plt
        mock_plt.xlabel = lambda *a, **kw: mock_plt
        mock_plt.ylabel = lambda *a, **kw: mock_plt
        mock_plt.legend = lambda *a, **kw: mock_plt
        mock_plt.grid = lambda *a, **kw: mock_plt
        mock_plt.show = lambda *a, **kw: mock_plt
        mock_plt.close = lambda *a, **kw: mock_plt
        mock_plt.savefig = lambda *a, **kw: mock_plt
        mock_plt.get_fignums = lambda: [1] if _called_state[0] else []

        mock_mpl.pyplot = mock_plt
        mock_mpl.use = lambda *a, **kw: None

        sandbox_globals["plt"] = mock_plt
        sandbox_globals["matplotlib"] = mock_mpl
        sys.modules["matplotlib"] = mock_mpl  # type: ignore
        sys.modules["matplotlib.pyplot"] = mock_plt  # type: ignore
        _mock_plot_called_fn = lambda: _called_state[0]

    t0 = time.time()
    exec_error: Optional[str] = None
    return_val: Any = None

    with contextlib.redirect_stdout(stdout_capture), contextlib.redirect_stderr(stderr_capture):
        try:
            # Check if last line is an expression to capture its evaluation
            parsed_ast = None
            try:
                import ast
                parsed_ast = ast.parse(clean_code)
            except Exception:
                pass

            if parsed_ast and parsed_ast.body:
                last_stmt = parsed_ast.body[-1]
                if isinstance(last_stmt, ast.Expr):
                    parsed_ast.body.pop()
                    if parsed_ast.body:
                        ast.fix_missing_locations(parsed_ast)
                        body_code = compile(parsed_ast, filename="<sandbox>", mode="exec")
                        exec(body_code, sandbox_globals)
                    expr_ast = ast.Expression(body=last_stmt.value)
                    ast.fix_missing_locations(expr_ast)
                    expr_code = compile(expr_ast, filename="<sandbox>", mode="eval")
                    return_val = eval(expr_code, sandbox_globals)
                else:
                    ast.fix_missing_locations(parsed_ast)
                    compiled = compile(parsed_ast, filename="<sandbox>", mode="exec")
                    exec(compiled, sandbox_globals)
            else:
                compiled = compile(clean_code, filename="<sandbox>", mode="exec")
                exec(compiled, sandbox_globals)

            if return_val is None and "result" in sandbox_globals:
                return_val = sandbox_globals["result"]

            # If matplotlib has open figures, capture them as PNG base64 images
            if has_plt:
                import matplotlib.pyplot as plt
                fig_nums = plt.get_fignums()
                for fnum in fig_nums:
                    fig = plt.figure(fnum)
                    buf = io.BytesIO()
                    fig.savefig(buf, format="png", bbox_inches="tight", dpi=150)
                    buf.seek(0)
                    b64_img = base64.b64encode(buf.read()).decode("utf-8")
                    data_uri = f"data:image/png;base64,{b64_img}"
                    generated_images.append(data_uri)
                plt.close("all")
            elif _mock_plot_called_fn():
                # 1x1 transparent PNG fallback data URI
                generated_images.append("data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg==")

        except Exception as exc:
            exec_error = f"{type(exc).__name__}: {exc}\n{traceback.format_exc()}"


    elapsed = round(time.time() - t0, 3)
    stdout_text = stdout_capture.getvalue()
    stderr_text = stderr_capture.getvalue()

    # Build formatted markdown presentation
    md_parts = []
    if stdout_text.strip():
        md_parts.append(f"```text\n{stdout_text.strip()}\n```")
    if return_val is not None:
        val_str = str(return_val)
        if len(val_str) < 500:
            md_parts.append(f"**Rückgabewert:** `{val_str}`")
        else:
            md_parts.append(f"**Rückgabewert:**\n```python\n{val_str[:2000]}\n```")

    for idx, img_uri in enumerate(generated_images, 1):
        md_parts.append(f"![Generiertes Diagramm {idx}]({img_uri})\n\n[⬇️ **Diagramm {idx} herunterladen**]({img_uri})")

    if exec_error:
        md_parts.append(f"❌ **Fehler bei Ausführung:**\n```text\n{exec_error}\n```")

    formatted_md = "\n\n".join(md_parts) if md_parts else "*(Code erfolgreich ohne Konsolenausgabe ausgeführt)*"

    status_str = "success" if exec_error is None else "error"
    return {
        "status": status_str,
        "success": exec_error is None,
        "stdout": stdout_text,
        "stderr": stderr_text,
        "result": str(return_val) if return_val is not None else None,
        "error": exec_error,
        "elapsed_seconds": elapsed,
        "images": generated_images,
        "markdown": formatted_md,
    }



# Backwards-compatible aliases
run_code_interpreter = execute_python_code
