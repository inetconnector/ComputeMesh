# SPDX-License-Identifier: Apache-2.0
"""
Safe Sandboxed Python & Mathematical Evaluation Tool.
Evaluates mathematical expressions, algorithms, and data calculations without security risks.
"""

from __future__ import annotations

import ast
import math
import statistics
import time
from typing import Any, Dict

# Allowed safe math and utility functions
SAFE_GLOBALS: Dict[str, Any] = {
    "math": math,
    "statistics": statistics,
    "abs": abs,
    "round": round,
    "min": min,
    "max": max,
    "sum": sum,
    "pow": pow,
    "len": len,
    "int": int,
    "float": float,
    "str": str,
    "list": list,
    "dict": dict,
    "tuple": tuple,
    "set": set,
    "range": range,
    "sorted": sorted,
    "pi": math.pi,
    "e": math.e,
}

# Forbidden AST node types that could execute arbitrary code or access system resources
FORBIDDEN_NODES = (
    ast.Import,
    ast.ImportFrom,
    ast.Exec if hasattr(ast, "Exec") else type(None),
    ast.Global,
    ast.Nonlocal,
    ast.Delete,
    ast.With,
    ast.AsyncWith,
    ast.Yield,
    ast.YieldFrom,
)


class SecurityValidator(ast.NodeVisitor):
    def __init__(self) -> None:
        self.is_safe = True
        self.error_msg = ""

    def visit(self, node: ast.AST) -> None:
        if isinstance(node, FORBIDDEN_NODES):
            self.is_safe = False
            self.error_msg = f"Forbidden operation '{type(node).__name__}'"
            return

        # Block any dunder or private attribute access (e.g. __class__, __subclasses__)
        if isinstance(node, ast.Attribute):
            if node.attr.startswith("__") or node.attr in ("co_code", "gi_frame", "f_locals", "tb_frame"):
                self.is_safe = False
                self.error_msg = f"Access to private attribute '{node.attr}' is prohibited"
                return

        # Block dangerous function names
        if isinstance(node, ast.Name):
            if node.id in ("eval", "exec", "open", "__import__", "compile", "globals", "locals", "vars", "getattr", "setattr", "delattr"):
                self.is_safe = False
                self.error_msg = f"Access to function '{node.id}' is prohibited"
                return

        super().visit(node)


def run_python_calc(
    expression: str = "",
    code: str = "",
    formula: str = "",
    query: str = "",
    timeout: float = 2.0,
) -> Dict[str, Any]:
    """
    Safely evaluates mathematical expressions, financial formulas, statistical calculations, or algorithms in Python.
    """
    raw_code = (expression or code or formula or query or "").strip()
    if not raw_code:
        return {"error": "Berechnungsausdruck darf nicht leer sein (z. B. '150000 * (0.038 / 12) / (1 - (1 + 0.038 / 12) ** -180)')."}

    # Basic length limit to prevent gigantic inputs
    if len(raw_code) > 2000:
        return {"error": "Ausdruck ist zu lang (maximal 2000 Zeichen)."}

    try:
        parsed_ast = ast.parse(raw_code, mode="exec")
    except SyntaxError as se:
        return {"error": f"Syntaxfehler im Ausdruck: {se.msg} (Zeile {se.lineno})"}

    validator = SecurityValidator()
    validator.visit(parsed_ast)
    if not validator.is_safe:
        return {"error": f"Sicherheitsrichtlinie verweigert die Ausführung: {validator.error_msg}"}

    local_scope: Dict[str, Any] = {}
    start_time = time.time()

    try:
        # If single expression, evaluate and return result
        if len(parsed_ast.body) == 1 and isinstance(parsed_ast.body[0], ast.Expr):
            eval_ast = ast.Expression(body=parsed_ast.body[0].value)
            compiled = compile(eval_ast, "<sandbox>", "eval")
            result = eval(compiled, {"__builtins__": None, **SAFE_GLOBALS}, local_scope)
        else:
            # Multi-line statement execution (assignments, loops)
            compiled = compile(parsed_ast, "<sandbox>", "exec")
            exec(compiled, {"__builtins__": None, **SAFE_GLOBALS}, local_scope)
            result = local_scope.get("result", local_scope)

        duration_ms = round((time.time() - start_time) * 1000, 2)
        return {
            "result": result,
            "expression": raw_code,
            "duration_ms": duration_ms,
            "status": "success",
        }
    except Exception as e:
        return {
            "error": f"Fehler bei Berechnung: {type(e).__name__}: {str(e)}",
            "expression": raw_code,
        }


# Backwards-compatible alias
calculate_math = run_python_calc
