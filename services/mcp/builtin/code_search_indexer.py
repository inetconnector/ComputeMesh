# SPDX-License-Identifier: Apache-2.0
"""High-Speed Code Search and AST Symbol Indexer for ComputeMesh."""

from __future__ import annotations

import ast
import fnmatch
import os
import re
from pathlib import Path
from typing import Any, Dict, List, Optional

EXCLUDED_DIRS = {".git", ".venv", "venv", "__pycache__", "node_modules", ".idea", ".vscode", "dist", "build", "target"}
MAX_FILE_SEARCH_SIZE_BYTES = 2 * 1024 * 1024  # 2 MB


def grep_search_code(
    query: str,
    search_path: str = ".",
    is_regex: bool = False,
    case_insensitive: bool = True,
    includes: Optional[List[str]] = None,
    max_results: int = 50,
) -> Dict[str, Any]:
    """Searches workspace files for code patterns with line numbers, regex support, and file filtering."""
    base_dir = os.path.abspath(str(search_path or ".").strip())
    if not os.path.exists(base_dir):
        return {"error": f"Pfad '{base_dir}' existiert nicht.", "matches": [], "total_matches": 0}

    flags = re.IGNORECASE if case_insensitive else 0
    pattern = re.compile(query if is_regex else re.escape(query), flags)
    matches: List[Dict[str, Any]] = []

    for root, dirs, files in os.walk(base_dir):
        dirs[:] = [d for d in dirs if d not in EXCLUDED_DIRS and not d.startswith(".pytest")]
        for fname in files:
            if len(matches) >= max_results:
                break
            if includes and not any(fnmatch.fnmatch(fname, pat) for pat in includes):
                continue

            full_path = os.path.join(root, fname)
            try:
                if os.path.getsize(full_path) > MAX_FILE_SEARCH_SIZE_BYTES:
                    continue
                with open(full_path, "r", encoding="utf-8", errors="ignore") as f:
                    for line_num, line in enumerate(f, start=1):
                        if pattern.search(line):
                            rel_path = os.path.relpath(full_path, base_dir)
                            matches.append({
                                "file": rel_path.replace("\\", "/"),
                                "absolute_path": full_path.replace("\\", "/"),
                                "line_number": line_num,
                                "line_content": line.rstrip("\r\n")[:300],
                            })
                            if len(matches) >= max_results:
                                break
            except Exception:
                continue

    return {
        "query": query,
        "search_path": base_dir.replace("\\", "/"),
        "total_matches": len(matches),
        "matches": matches,
    }


def extract_code_symbols(file_path: str) -> Dict[str, Any]:
    """Extracts top-level symbols (classes, functions, structs, interfaces) using AST or syntax parsing."""
    clean_path = os.path.abspath(str(file_path or "").strip())
    if not os.path.isfile(clean_path):
        return {"error": f"Datei '{clean_path}' existiert nicht.", "symbols": []}

    ext = os.path.splitext(clean_path)[1].lower()
    symbols: List[Dict[str, Any]] = []

    try:
        with open(clean_path, "r", encoding="utf-8", errors="replace") as f:
            code_text = f.read()

        if ext == ".py":
            tree = ast.parse(code_text, filename=clean_path)
            for node in tree.body:
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    symbols.append({
                        "name": node.name,
                        "kind": "async_function" if isinstance(node, ast.AsyncFunctionDef) else "function",
                        "line": node.lineno,
                        "end_line": getattr(node, "end_lineno", node.lineno),
                        "docstring": ast.get_docstring(node) or "",
                    })
                elif isinstance(node, ast.ClassDef):
                    methods = [
                        m.name for m in node.body if isinstance(m, (ast.FunctionDef, ast.AsyncFunctionDef))
                    ]
                    symbols.append({
                        "name": node.name,
                        "kind": "class",
                        "line": node.lineno,
                        "end_line": getattr(node, "end_lineno", node.lineno),
                        "methods": methods,
                        "docstring": ast.get_docstring(node) or "",
                    })
        elif ext == ".go":
            for idx, line in enumerate(code_text.splitlines(), start=1):
                func_m = re.match(r"^func\s+(?:\((.*?)\)\s+)?([A-Za-z0-9_]+)\s*\(", line)
                if func_m:
                    recv, fname = func_m.groups()
                    symbols.append({"name": fname, "kind": "method" if recv else "function", "receiver": recv or "", "line": idx})
                type_m = re.match(r"^type\s+([A-Za-z0-9_]+)\s+(struct|interface)", line)
                if type_m:
                    tname, tkind = type_m.groups()
                    symbols.append({"name": tname, "kind": tkind, "line": idx})
        else:
            # Generic JS/TS/Kotlin pattern extraction
            for idx, line in enumerate(code_text.splitlines(), start=1):
                match = re.search(r"\b(class|interface|function|fun|enum)\s+([A-Za-z0-9_]+)", line)
                if match:
                    kind, name = match.groups()
                    symbols.append({"name": name, "kind": kind, "line": idx})

        return {
            "file": clean_path.replace("\\", "/"),
            "language": ext.lstrip("."),
            "total_symbols": len(symbols),
            "symbols": symbols,
        }
    except Exception as exc:
        return {"error": f"Symbol-Extraktionsfehler: {exc}", "symbols": []}
