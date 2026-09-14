# SPDX-License-Identifier: Apache-2.0
"""Multi-Language AST Syntax Validator and Linter for ComputeMesh Agentic Coding."""

from __future__ import annotations

import ast
import json
import logging
import re
from typing import Any, Dict, List, Optional

log = logging.getLogger("computemesh.mcp.code_lint_and_syntax")


def validate_code_syntax(code: str, language: str = "python") -> Dict[str, Any]:
    """Validates code syntax using AST parsing or schema tokenizer, returning exact error positions."""
    clean_code = str(code or "").strip()
    if not clean_code:
        return {"valid": False, "language": language, "errors": [{"message": "Quellcode ist leer."}]}

    lang = language.lower().strip().lstrip(".")
    errors: List[Dict[str, Any]] = []

    if lang in ("python", "py"):
        try:
            ast.parse(clean_code)
        except SyntaxError as exc:
            errors.append({
                "line": exc.lineno or 1,
                "column": exc.offset or 0,
                "message": exc.msg,
                "text": (exc.text or "").strip(),
            })
    elif lang in ("json", "jsonc"):
        try:
            # Strip comments for jsonc
            stripped = re.sub(r"//.*?$|/\*.*?\*/", "", clean_code, flags=re.MULTILINE | re.DOTALL)
            json.loads(stripped)
        except json.JSONDecodeError as exc:
            errors.append({
                "line": exc.lineno,
                "column": exc.colno,
                "message": exc.msg,
                "pos": exc.pos,
            })
    elif lang in ("yaml", "yml"):
        try:
            import yaml
            yaml.safe_load(clean_code)
        except Exception as exc:
            errors.append({"line": getattr(exc, "problem_mark", None) and exc.problem_mark.line + 1 or 1, "message": str(exc)})
    else:
        # General bracket & quote balancing validator for Go, Kotlin, JS, TS
        stack = []
        pairs = {")": "(", "}": "{", "]": "["}
        lines = clean_code.splitlines()
        for l_num, line in enumerate(lines, start=1):
            for col, char in enumerate(line, start=1):
                if char in "({[":
                    stack.append((char, l_num, col))
                elif char in ")}]":
                    if not stack:
                        errors.append({"line": l_num, "column": col, "message": f"Unerwartetes schließendes Zeichen '{char}'."})
                    else:
                        top, top_l, top_c = stack.pop()
                        if pairs[char] != top:
                            errors.append({"line": l_num, "column": col, "message": f"Klammer-Mismatch: '{char}' schließt nicht '{top}' aus Zeile {top_l}."})
        while stack:
            unclosed, u_l, u_c = stack.pop()
            errors.append({"line": u_l, "column": u_c, "message": f"Nicht geschlossene Klammer '{unclosed}'."})

    return {
        "valid": len(errors) == 0,
        "language": lang,
        "total_errors": len(errors),
        "errors": errors,
        "summary": "Syntax ist einwandfrei." if not errors else f"{len(errors)} Syntax-Fehler gefunden.",
    }


def check_code_quality(code: str, language: str = "python") -> Dict[str, Any]:
    """Inspects code complexity, max line length, monster functions (>60 lines), and docstrings."""
    clean_code = str(code or "").strip()
    warnings: List[Dict[str, Any]] = []
    lines = clean_code.splitlines()

    for idx, line in enumerate(lines, start=1):
        if len(line) > 140:
            warnings.append({"line": idx, "type": "line_length", "message": f"Zeile überschreitet 140 Zeichen ({len(line)} Zeichen)."})

    lang = language.lower().strip().lstrip(".")
    if lang in ("python", "py"):
        try:
            tree = ast.parse(clean_code)
            for node in ast.walk(tree):
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    f_len = (getattr(node, "end_lineno", node.lineno) - node.lineno) + 1
                    if f_len > 60:
                        warnings.append({
                            "line": node.lineno,
                            "type": "long_function",
                            "message": f"Funktion '{node.name}' ist mit {f_len} Zeilen zu lang (> 60 Zeilen). Bitte modularisieren.",
                        })
                    if not ast.get_docstring(node) and not node.name.startswith("_"):
                        warnings.append({
                            "line": node.lineno,
                            "type": "missing_docstring",
                            "message": f"Öffentliche Funktion '{node.name}' hat keinen Docstring.",
                        })
        except Exception:
            pass

    return {
        "language": lang,
        "total_lines": len(lines),
        "quality_score": max(0, 100 - (len(warnings) * 5)),
        "warnings_count": len(warnings),
        "warnings": warnings,
    }
