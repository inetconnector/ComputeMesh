# SPDX-License-Identifier: Apache-2.0
"""Safe Workspace and Local Filesystem Inspection Tools."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Dict, List, Optional

MAX_READ_BYTES = 500_000
MAX_LIST_ENTRIES = 200


def _get_safe_workspace_root() -> Path:
    return Path(os.getcwd()).resolve()


def _resolve_safe_path(rel_path: str) -> Optional[Path]:
    root = _get_safe_workspace_root()
    clean = str(rel_path or ".").strip().replace("\\", "/")
    if clean.startswith("/"):
        clean = clean.lstrip("/")
    target = (root / clean).resolve()
    try:
        target.relative_to(root)
        return target
    except ValueError:
        return None


def list_workspace_files(
    relative_path: str = ".",
    pattern: Optional[str] = None,
    max_depth: int = 3,
) -> Dict[str, Any]:
    """Safely lists files and directories in the workspace under the specified path."""
    target_dir = _resolve_safe_path(relative_path)
    if not target_dir or not target_dir.exists() or not target_dir.is_dir():
        return {"error": f"Verzeichnis '{relative_path}' existiert nicht oder liegt außerhalb des Workspace."}

    entries: List[Dict[str, Any]] = []
    root = _get_safe_workspace_root()

    try:
        depth_limit = max(1, min(5, int(max_depth)))
        for current_root, dirs, files in os.walk(str(target_dir)):
            curr_path = Path(current_root)
            depth = len(curr_path.relative_to(target_dir).parts)
            if depth >= depth_limit:
                dirs.clear()

            # Filter out hidden or venv directories
            dirs[:] = [d for d in dirs if not d.startswith((".", "__pycache__", "node_modules", "venv", ".git"))]

            for d in dirs:
                if len(entries) >= MAX_LIST_ENTRIES:
                    break
                p = curr_path / d
                entries.append({
                    "name": d,
                    "path": str(p.relative_to(root)).replace("\\", "/"),
                    "type": "directory",
                })

            for f in sorted(files):
                if len(entries) >= MAX_LIST_ENTRIES:
                    break
                if f.startswith("."):
                    continue
                if pattern and not Path(f).match(pattern):
                    continue
                p = curr_path / f
                try:
                    sz = p.stat().st_size
                except Exception:
                    sz = 0
                entries.append({
                    "name": f,
                    "path": str(p.relative_to(root)).replace("\\", "/"),
                    "type": "file",
                    "size_bytes": sz,
                })
    except Exception as exc:
        return {"error": f"Fehler beim Auflisten von '{relative_path}': {exc}"}

    return {
        "status": "success",
        "relative_path": relative_path,
        "total_entries": len(entries),
        "truncated": len(entries) >= MAX_LIST_ENTRIES,
        "entries": entries,
    }


def read_workspace_file(
    relative_path: str,
    max_lines: int = 200,
    offset_line: int = 1,
) -> Dict[str, Any]:
    """Safely reads lines from a workspace text file with boundary checks."""
    target_file = _resolve_safe_path(relative_path)
    if not target_file or not target_file.exists() or not target_file.is_file():
        return {"error": f"Datei '{relative_path}' wurde nicht gefunden oder liegt außerhalb des Workspace."}

    try:
        file_size = target_file.stat().st_size
        if file_size > MAX_READ_BYTES * 20:
            return {"error": f"Datei '{relative_path}' ist zu groß ({file_size / (1024*1024):.1f} MB, Limit: 10 MB)."}

        with open(target_file, "r", encoding="utf-8", errors="replace") as f:
            all_lines = f.readlines()

        total_lines = len(all_lines)
        start_idx = max(0, int(offset_line) - 1)
        limit = max(1, min(1000, int(max_lines)))
        end_idx = min(total_lines, start_idx + limit)

        sliced = all_lines[start_idx:end_idx]
        content_text = "".join(sliced)

        return {
            "status": "success",
            "file": str(relative_path).replace("\\", "/"),
            "total_lines": total_lines,
            "start_line": start_idx + 1,
            "end_line": end_idx,
            "lines_read": len(sliced),
            "content": content_text,
        }
    except Exception as exc:
        return {"error": f"Fehler beim Lesen der Datei '{relative_path}': {exc}"}


def write_workspace_file(
    relative_path: str,
    content: str,
    overwrite: bool = True,
    create_dirs: bool = True,
) -> Dict[str, Any]:
    """Safely writes UTF-8 text content to a file in the workspace with atomic write and auto-directory creation."""
    target_file = _resolve_safe_path(relative_path)
    if not target_file:
        return {"error": f"Pfad '{relative_path}' liegt außerhalb des erlaubten Workspace-Bereichs.", "success": False}

    already_exists = target_file.exists() and target_file.is_file()
    if already_exists and not overwrite:
        return {"error": f"Datei '{relative_path}' existiert bereits und overwrite=False ist gesetzt.", "success": False}

    try:
        if create_dirs:
            target_file.parent.mkdir(parents=True, exist_ok=True)

        norm_content = str(content or "").replace("\r\n", "\n")
        
        # Write atomically using a temporary file in the same directory
        temp_path = target_file.with_name(f".tmp_{target_file.name}_{os.getpid()}")
        with open(temp_path, "w", encoding="utf-8", newline="\n") as f:
            f.write(norm_content)
        
        if target_file.exists():
            target_file.unlink()
        temp_path.rename(target_file)

        line_count = len(norm_content.splitlines())
        byte_size = len(norm_content.encode("utf-8"))

        return {
            "status": "success",
            "success": True,
            "file": str(relative_path).replace("\\", "/"),
            "absolute_path": str(target_file).replace("\\", "/"),
            "lines_written": line_count,
            "size_bytes": byte_size,
            "overwritten": already_exists,
        }
    except Exception as exc:
        return {"error": f"Fehler beim Schreiben der Datei '{relative_path}': {exc}", "success": False}

