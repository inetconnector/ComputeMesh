# SPDX-License-Identifier: Apache-2.0
"""Transactional Workspace Quarantine and Shadow Staging Engine."""

from __future__ import annotations

import ast
import difflib
import json
import logging
import os
import shutil
import time
import uuid
from typing import Any, Dict, List, Optional

log = logging.getLogger("computemesh.mcp.quarantine")
QUARANTINE_DIR_NAME = ".computemesh-quarantine"


def _get_quarantine_root(workspace_root: Optional[str] = None) -> str:
    root = os.path.abspath(workspace_root or ".")
    q_dir = os.path.join(root, QUARANTINE_DIR_NAME)
    os.makedirs(q_dir, exist_ok=True)
    return q_dir


def quarantine_stage_files(
    files: Dict[str, str],
    workspace_root: Optional[str] = None,
    txn_id: Optional[str] = None,
) -> Dict[str, Any]:
    """Stages proposed file modifications in an isolated quarantine sandbox."""
    if not files:
        return {"error": "Keine Dateien zum Staging übergeben.", "success": False}

    root = os.path.abspath(workspace_root or ".")
    t_id = txn_id or f"txn_{int(time.time())}_{uuid.uuid4().hex[:6]}"
    txn_dir = os.path.join(_get_quarantine_root(root), t_id)
    orig_dir = os.path.join(txn_dir, "original")
    staged_dir = os.path.join(txn_dir, "staged")
    os.makedirs(orig_dir, exist_ok=True)
    os.makedirs(staged_dir, exist_ok=True)

    diffs: Dict[str, str] = {}
    manifest_files = []

    for rel_path, staged_content in files.items():
        clean_rel = rel_path.strip().replace("\\", "/").lstrip("/")
        real_target = os.path.abspath(os.path.join(root, clean_rel))

        # Security check: must remain within workspace root
        if not real_target.startswith(root):
            return {"error": f"Pfad '{rel_path}' verlässt das Workspace-Verzeichnis.", "success": False}

        orig_content = ""
        if os.path.exists(real_target) and os.path.isfile(real_target):
            with open(real_target, "r", encoding="utf-8", errors="replace") as f:
                orig_content = f.read()

        # Save original and staged
        orig_file = os.path.join(orig_dir, clean_rel)
        staged_file = os.path.join(staged_dir, clean_rel)
        os.makedirs(os.path.dirname(orig_file), exist_ok=True)
        os.makedirs(os.path.dirname(staged_file), exist_ok=True)

        with open(orig_file, "w", encoding="utf-8") as f:
            f.write(orig_content)
        with open(staged_file, "w", encoding="utf-8") as f:
            f.write(staged_content)

        # Generate Unified Diff
        orig_lines = orig_content.splitlines(keepends=True)
        staged_lines = staged_content.splitlines(keepends=True)
        diff_lines = list(difflib.unified_diff(orig_lines, staged_lines, fromfile=f"a/{clean_rel}", tofile=f"b/{clean_rel}"))
        diff_text = "".join(diff_lines)
        diffs[clean_rel] = diff_text

        manifest_files.append({
            "path": clean_rel,
            "exists_before": os.path.exists(real_target),
            "orig_size": len(orig_content),
            "staged_size": len(staged_content),
            "diff_lines": len(diff_lines),
        })

    manifest = {
        "txn_id": t_id,
        "created_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "workspace_root": root,
        "files": manifest_files,
        "status": "staged",
    }
    with open(os.path.join(txn_dir, "manifest.json"), "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2)

    return {
        "success": True,
        "txn_id": t_id,
        "staged_files_count": len(files),
        "files": manifest_files,
        "diffs": diffs,
    }


def quarantine_validate(txn_id: str, workspace_root: Optional[str] = None) -> Dict[str, Any]:
    """Validates syntax and AST of all staged files in the quarantine transaction."""
    root = os.path.abspath(workspace_root or ".")
    txn_dir = os.path.join(_get_quarantine_root(root), txn_id)
    manifest_path = os.path.join(txn_dir, "manifest.json")
    if not os.path.exists(manifest_path):
        return {"error": f"Transaktion '{txn_id}' nicht gefunden.", "success": False}

    with open(manifest_path, "r", encoding="utf-8") as f:
        manifest = json.load(f)

    staged_dir = os.path.join(txn_dir, "staged")
    errors: List[Dict[str, Any]] = []

    for f_meta in manifest.get("files", []):
        clean_rel = f_meta.get("path", "")
        staged_file = os.path.join(staged_dir, clean_rel)
        if not os.path.exists(staged_file):
            continue

        with open(staged_file, "r", encoding="utf-8", errors="replace") as f:
            code = f.read()

        if clean_rel.endswith(".py"):
            try:
                ast.parse(code, filename=clean_rel)
            except SyntaxError as exc:
                errors.append({"file": clean_rel, "line": exc.lineno, "message": str(exc.msg)})
        elif clean_rel.endswith(".json"):
            try:
                json.loads(code)
            except Exception as exc:
                errors.append({"file": clean_rel, "message": f"Ungültiges JSON: {exc}"})

    is_valid = len(errors) == 0
    return {
        "success": is_valid,
        "txn_id": txn_id,
        "valid": is_valid,
        "total_errors": len(errors),
        "errors": errors,
    }


def quarantine_commit(txn_id: str, workspace_root: Optional[str] = None) -> Dict[str, Any]:
    """Atomically commits staged quarantine files into the active workspace."""
    root = os.path.abspath(workspace_root or ".")
    txn_dir = os.path.join(_get_quarantine_root(root), txn_id)
    manifest_path = os.path.join(txn_dir, "manifest.json")
    if not os.path.exists(manifest_path):
        return {"error": f"Transaktion '{txn_id}' nicht gefunden.", "success": False}

    with open(manifest_path, "r", encoding="utf-8") as f:
        manifest = json.load(f)

    staged_dir = os.path.join(txn_dir, "staged")
    applied = []

    for f_meta in manifest.get("files", []):
        clean_rel = f_meta.get("path", "")
        src_path = os.path.join(staged_dir, clean_rel)
        dst_path = os.path.join(root, clean_rel)
        os.makedirs(os.path.dirname(dst_path), exist_ok=True)
        shutil.copy2(src_path, dst_path)
        applied.append(clean_rel)

    shutil.rmtree(txn_dir, ignore_errors=True)
    return {
        "success": True,
        "txn_id": txn_id,
        "committed_files": applied,
        "total_committed": len(applied),
    }


def quarantine_rollback(txn_id: str, workspace_root: Optional[str] = None) -> Dict[str, Any]:
    """Discards the staged quarantine transaction without touching the workspace."""
    root = os.path.abspath(workspace_root or ".")
    txn_dir = os.path.join(_get_quarantine_root(root), txn_id)
    if not os.path.exists(txn_dir):
        return {"error": f"Transaktion '{txn_id}' nicht gefunden.", "success": False}

    shutil.rmtree(txn_dir, ignore_errors=True)
    return {"success": True, "txn_id": txn_id, "status": "rolled_back"}
