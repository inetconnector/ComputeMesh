"""ComputeMesh Node Local Workspace & Project Path Manager.

Allows local nodes (Windows Tray App, Linux Appliance, Headless) to register,
persist, and report authentic local project directory paths to the ControlPlane/Portal.
Zero mocks, zero hardcoded dummies: only valid paths existing on the host filesystem.
"""
from __future__ import annotations

import json
import logging
import os
import re
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

logger = logging.getLogger("WorkspaceManager")


def get_workspace_config_path() -> Path:
    """Return the platform-appropriate path for workspaces.json."""
    if sys.platform == "win32":
        app_data = os.environ.get("APPDATA")
        if app_data:
            base_dir = Path(app_data) / "ComputeMesh"
        else:
            base_dir = Path.home() / ".computemesh"
    else:
        base_dir = Path.home() / ".computemesh"
    base_dir.mkdir(parents=True, exist_ok=True)
    return base_dir / "workspaces.json"


def detect_git_branch(project_dir: Path) -> str:
    """Detect current git branch if the project is a git repository."""
    head_file = project_dir / ".git" / "HEAD"
    if head_file.is_file():
        try:
            content = head_file.read_text(encoding="utf-8").strip()
            if content.startswith("ref: refs/heads/"):
                return content[len("ref: refs/heads/"):].strip()
            return content[:8]
        except (OSError, UnicodeDecodeError):
            pass
    # Submodule .git file pointer (gitdir: ...)
    git_file = project_dir / ".git"
    if git_file.is_file():
        try:
            txt = git_file.read_text(encoding="utf-8").strip()
            if txt.startswith("gitdir:"):
                gitdir_rel = txt[len("gitdir:"):].strip()
                target_head = (project_dir / gitdir_rel / "HEAD").resolve()
                if target_head.is_file():
                    content = target_head.read_text(encoding="utf-8").strip()
                    if content.startswith("ref: refs/heads/"):
                        return content[len("ref: refs/heads/"):].strip()
                    return content[:8]
        except (OSError, UnicodeDecodeError):
            pass
    return ""


def _slugify(name: str) -> str:
    slug = re.sub(r"[^\w\-_.]", "-", name.strip().lower())
    return re.sub(r"-+", "-", slug).strip("-") or "project"


def load_local_workspaces() -> list[dict[str, Any]]:
    """Load authentic registered workspaces from persistent storage.
    
    If empty, checks if the current working directory is a valid project workspace
    and auto-registers it so the user's host repo is immediately available.
    """
    cfg_path = get_workspace_config_path()
    workspaces: list[dict[str, Any]] = []

    if cfg_path.is_file():
        try:
            raw = cfg_path.read_text(encoding="utf-8")
            data = json.loads(raw)
            if isinstance(data, dict) and "workspaces" in data:
                items = data["workspaces"]
            elif isinstance(data, list):
                items = data
            else:
                items = []

            for item in items:
                if not isinstance(item, dict):
                    continue
                p_str = item.get("path")
                if not p_str:
                    continue
                p = Path(p_str)
                # Verify directory exists
                if p.is_dir():
                    branch = detect_git_branch(p)
                    workspaces.append({
                        "id": item.get("id") or _slugify(p.name),
                        "name": item.get("name") or p.name,
                        "path": str(p.resolve()),
                        "git_branch": branch or item.get("git_branch", ""),
                        "registered_at": item.get("registered_at", time.time()),
                        "last_active": item.get("last_active", time.time()),
                    })
        except Exception as exc:
            logger.warning("Failed to load workspaces config %s: %s", cfg_path, exc)

    # Auto-register current repository if nothing registered yet
    if not workspaces:
        try:
            cwd = Path.cwd().resolve()
            if (cwd / ".git").exists() or (cwd / "README.md").exists():
                registered = register_local_workspace(str(cwd))
                if registered:
                    workspaces.append(registered)
        except Exception as exc:
            logger.debug("Auto-register cwd skipped: %s", exc)

    return workspaces


def register_local_workspace(path_str: str, custom_name: str | None = None) -> dict[str, Any] | None:
    """Register a local directory path as a managed project workspace."""
    p = Path(path_str).resolve()
    if not p.is_dir():
        logger.warning("Cannot register non-existent directory: %s", path_str)
        return None

    name = (custom_name or p.name).strip()
    ws_id = _slugify(name)
    branch = detect_git_branch(p)

    new_entry = {
        "id": ws_id,
        "name": name,
        "path": str(p),
        "git_branch": branch,
        "registered_at": time.time(),
        "last_active": time.time(),
    }

    workspaces = load_local_workspaces()
    # Check if already present by path or id
    updated = False
    for idx, existing in enumerate(workspaces):
        if existing["path"] == str(p) or existing["id"] == ws_id:
            workspaces[idx] = new_entry
            updated = True
            break
    if not updated:
        workspaces.append(new_entry)

    _save_workspaces(workspaces)
    logger.info("Registered local workspace '%s' at %s", name, str(p))
    return new_entry


def unregister_local_workspace(ws_id_or_path: str) -> bool:
    """Unregister a workspace by ID or full path."""
    workspaces = load_local_workspaces()
    original_len = len(workspaces)
    filtered = [w for w in workspaces if w["id"] != ws_id_or_path and w["path"] != ws_id_or_path]
    if len(filtered) != original_len:
        _save_workspaces(filtered)
        logger.info("Unregistered workspace %s", ws_id_or_path)
        return True
    return False


def _save_workspaces(workspaces: list[dict[str, Any]]) -> None:
    cfg_path = get_workspace_config_path()
    try:
        payload = {
            "version": 1,
            "updated_at": time.time(),
            "workspaces": workspaces,
        }
        temp_path = cfg_path.with_suffix(".tmp")
        temp_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        temp_path.replace(cfg_path)
    except Exception as exc:
        logger.error("Failed to write workspaces to %s: %s", cfg_path, exc)

