# SPDX-License-Identifier: Apache-2.0
"""High-Precision Code Patch Engine for ComputeMesh Agentic Coding."""

from __future__ import annotations

import difflib
import logging
import os
from pathlib import Path
from typing import Any, Dict, List, Optional

log = logging.getLogger("computemesh.mcp.code_patch_engine")


def replace_file_content(
    file_path: str,
    target_content: str,
    replacement_content: str,
    start_line: Optional[int] = None,
    end_line: Optional[int] = None,
    allow_multiple: bool = False,
) -> Dict[str, Any]:
    """Replaces exact code blocks in a target file with line range bounds and rollback protection."""
    clean_path = os.path.abspath(str(file_path or "").strip())
    if not os.path.isfile(clean_path):
        return {"error": f"Datei '{clean_path}' existiert nicht.", "success": False}

    try:
        with open(clean_path, "r", encoding="utf-8", errors="replace") as f:
            original_text = f.read()

        lines = original_text.splitlines(keepends=True)
        total_lines = len(lines)

        s_idx = max(0, (start_line - 1) if start_line is not None else 0)
        e_idx = min(total_lines, end_line if end_line is not None else total_lines)

        search_window = "".join(lines[s_idx:e_idx])
        norm_target = target_content.replace("\r\n", "\n")
        norm_window = search_window.replace("\r\n", "\n")

        if norm_target not in norm_window:
            return {
                "error": f"Zielinhalt nicht im angegebenen Zeilenbereich [{s_idx+1}:{e_idx}] gefunden.",
                "success": False,
                "file_path": clean_path,
            }

        count = norm_window.count(norm_target)
        if count > 1 and not allow_multiple:
            return {
                "error": f"Zielinhalt kommt {count}-mal im Suchbereich vor. Bitte Zeilenbereich eingrenzen oder allow_multiple=True setzen.",
                "success": False,
            }

        new_window = norm_window.replace(norm_target, replacement_content.replace("\r\n", "\n"), 1 if not allow_multiple else -1)
        prefix = "".join(lines[:s_idx])
        suffix = "".join(lines[e_idx:])
        new_text = prefix + new_window + suffix

        # Generate diff preview
        diff = list(difflib.unified_diff(
            original_text.splitlines(keepends=True),
            new_text.splitlines(keepends=True),
            fromfile=f"a/{os.path.basename(clean_path)}",
            tofile=f"b/{os.path.basename(clean_path)}",
            n=3,
        ))

        with open(clean_path, "w", encoding="utf-8") as f:
            f.write(new_text)

        return {
            "success": True,
            "file_path": clean_path,
            "replacements_count": count,
            "diff": "".join(diff),
            "total_lines": len(new_text.splitlines()),
        }
    except Exception as exc:
        return {"error": f"Fehler beim Patchen der Datei: {exc}", "success": False}


def multi_replace_file_content(
    file_path: str,
    replacement_chunks: List[Dict[str, Any]],
) -> Dict[str, Any]:
    """Applies multiple non-contiguous replacement chunks to a single file with atomic rollback."""
    clean_path = os.path.abspath(str(file_path or "").strip())
    if not os.path.isfile(clean_path):
        return {"error": f"Datei '{clean_path}' existiert nicht.", "success": False}

    try:
        with open(clean_path, "r", encoding="utf-8", errors="replace") as f:
            original_text = f.read()

        current_text = original_text
        diff_all: List[str] = []
        applied_count = 0

        # Sort chunks in reverse order by start_line to avoid index shift
        sorted_chunks = sorted(
            replacement_chunks,
            key=lambda c: int(c.get("start_line") or c.get("StartLine") or 0),
            reverse=True,
        )

        for chunk in sorted_chunks:
            target = str(chunk.get("target_content") or chunk.get("TargetContent") or "")
            repl = str(chunk.get("replacement_content") or chunk.get("ReplacementContent") or "")
            s_line = chunk.get("start_line") or chunk.get("StartLine")
            e_line = chunk.get("end_line") or chunk.get("EndLine")
            allow_mult = bool(chunk.get("allow_multiple") or chunk.get("AllowMultiple", False))

            if not target:
                continue

            lines = current_text.splitlines(keepends=True)
            s_idx = max(0, (int(s_line) - 1) if s_line else 0)
            e_idx = min(len(lines), int(e_line) if e_line else len(lines))

            window = "".join(lines[s_idx:e_idx]).replace("\r\n", "\n")
            norm_target = target.replace("\r\n", "\n")

            if norm_target not in window:
                return {
                    "error": f"Chunk-Zielinhalt nicht im Bereich [{s_idx+1}:{e_idx}] gefunden: '{target[:40]}...'",
                    "success": False,
                    "applied_before_failure": applied_count,
                }

            new_window = window.replace(norm_target, repl.replace("\r\n", "\n"), 1 if not allow_mult else -1)
            current_text = "".join(lines[:s_idx]) + new_window + "".join(lines[e_idx:])
            applied_count += 1

        diff = list(difflib.unified_diff(
            original_text.splitlines(keepends=True),
            current_text.splitlines(keepends=True),
            fromfile=f"a/{os.path.basename(clean_path)}",
            tofile=f"b/{os.path.basename(clean_path)}",
            n=3,
        ))

        with open(clean_path, "w", encoding="utf-8") as f:
            f.write(current_text)

        return {
            "success": True,
            "file_path": clean_path,
            "chunks_applied": applied_count,
            "diff": "".join(diff),
            "total_lines": len(current_text.splitlines()),
        }
    except Exception as exc:
        return {"error": f"Fehler bei Multi-Chunk-Ersetzung: {exc}", "success": False}
