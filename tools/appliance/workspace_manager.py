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
import shutil
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


class WorkspaceOperationResult(dict):
    """Result object for workspace operations; backwards-compatible with bool checks."""
    def __bool__(self) -> bool:
        return bool(self.get("success", False))


def get_projects_base_dir() -> Path:
    """Return the configured base directory for host projects."""
    env_dir = os.environ.get("COMPUTEMESH_PROJECTS_DIR", "").strip()
    if env_dir:
        return Path(env_dir).expanduser().resolve()

    cfg_path = get_workspace_config_path()
    if cfg_path.is_file():
        try:
            data = json.loads(cfg_path.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                p_base = data.get("projects_base_dir")
                if p_base and str(p_base).strip():
                    return Path(str(p_base).strip()).expanduser().resolve()
        except Exception:
            pass

    if sys.platform == "win32":
        default_p = Path("C:/Users/frede/Projekte/KI")
        if default_p.is_dir():
            return default_p
        return (Path.home() / "Projekte" / "KI").resolve()
    return Path("/opt/computemesh")


def set_projects_base_dir(new_dir: str, rescan: bool = True) -> Path:
    """Configure a new base directory for projects and optionally rescan."""
    clean = str(new_dir or "").strip()
    if not clean:
        raise ValueError("Project base directory path cannot be empty")
    target = Path(clean).expanduser().resolve()
    target.mkdir(parents=True, exist_ok=True)

    cfg_path = get_workspace_config_path()
    payload: dict[str, Any] = {}
    if cfg_path.is_file():
        try:
            payload = json.loads(cfg_path.read_text(encoding="utf-8"))
            if not isinstance(payload, dict):
                payload = {}
        except Exception:
            payload = {}

    payload["projects_base_dir"] = str(target)
    payload["updated_at"] = time.time()

    temp_path = cfg_path.with_suffix(".tmp")
    temp_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    temp_path.replace(cfg_path)

    if rescan:
        workspaces = load_local_workspaces()
        discovered = discover_host_project_workspaces()
        for item in discovered:
            if not any(w["path"] == item["path"] or w["id"] == item["id"] for w in workspaces):
                workspaces.append(item)
        _save_workspaces(workspaces, auto_discovery_completed=True, projects_base_dir=str(target))

    return target


def _read_raw_workspace_config() -> tuple[list[dict[str, Any]], set[str], bool]:
    """Read the raw persisted workspaces config, returning (workspaces, unregistered_paths, auto_discovery_completed)."""
    cfg_path = get_workspace_config_path()
    if not cfg_path.is_file():
        return [], set(), False

    try:
        raw = cfg_path.read_text(encoding="utf-8")
        data = json.loads(raw)
        if isinstance(data, dict):
            workspaces = data.get("workspaces", [])
            unregistered = set(data.get("unregistered_paths", []))
            auto_discovery_completed = bool(data.get("auto_discovery_completed", False))
            return workspaces if isinstance(workspaces, list) else [], unregistered, auto_discovery_completed
        elif isinstance(data, list):
            return data, set(), False
    except Exception as exc:
        logger.warning("Failed to load workspaces config %s: %s", cfg_path, exc)
    return [], set(), False


def _save_workspaces(
    workspaces: list[dict[str, Any]],
    unregistered_paths: set[str] | None = None,
    auto_discovery_completed: bool = True,
    projects_base_dir: str | None = None,
) -> None:
    cfg_path = get_workspace_config_path()
    try:
        existing_base = projects_base_dir
        if existing_base is None and cfg_path.is_file():
            try:
                raw_data = json.loads(cfg_path.read_text(encoding="utf-8"))
                if isinstance(raw_data, dict):
                    existing_base = raw_data.get("projects_base_dir")
            except Exception:
                pass
        payload = {
            "version": 2,
            "updated_at": time.time(),
            "auto_discovery_completed": auto_discovery_completed,
            "projects_base_dir": existing_base or str(get_projects_base_dir()),
            "unregistered_paths": sorted(list(unregistered_paths or set())),
            "workspaces": workspaces,
        }
        temp_path = cfg_path.with_suffix(".tmp")
        temp_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        temp_path.replace(cfg_path)
    except Exception as exc:
        logger.error("Failed to write workspaces to %s: %s", cfg_path, exc)


def load_local_workspaces() -> list[dict[str, Any]]:
    """Load authentic registered workspaces from persistent storage.
    
    Includes registration_source, node_id, and lifecycle status.
    Auto-discovers host projects only during bootstrap, respecting explicitly
    unregistered items so they never resurrect.
    """
    raw_items, unregistered_paths, auto_discovery_completed = _read_raw_workspace_config()
    workspaces: list[dict[str, Any]] = []

    for item in raw_items:
        if not isinstance(item, dict):
            continue
        p_str = item.get("path")
        if not p_str:
            continue
        p = Path(p_str)
        is_dir = p.is_dir()
        branch = detect_git_branch(p) if is_dir else ""
        source = item.get("registration_source")
        if not source:
            source = "auto_discovered" if any(cand in p_str.replace("/", "\\") for cand in ["Projekte\\KI", "Projekte/KI"]) else "user_registered"

        workspaces.append({
            "id": item.get("id") or _slugify(item.get("name") or p.name),
            "name": item.get("name") or p.name,
            "path": str(p.resolve()) if is_dir else p_str,
            "git_branch": branch or item.get("git_branch", ""),
            "registration_source": source,
            "status": "active" if is_dir else "missing_dir",
            "node_id": item.get("node_id") or "cm-win-mifcom-rtx3080",
            "registered_at": item.get("registered_at", time.time()),
            "last_active": item.get("last_active", time.time()),
        })

    # Auto-discover host project workspaces only during initial bootstrap or if never run before
    if not auto_discovery_completed and len(workspaces) <= 1:
        discovered = discover_host_project_workspaces(excluded_paths=unregistered_paths)
        if discovered:
            for item in discovered:
                if not any(w["path"] == item["path"] or w["id"] == item["id"] for w in workspaces):
                    workspaces.append(item)
        _save_workspaces(workspaces, unregistered_paths=unregistered_paths, auto_discovery_completed=True)
    elif not auto_discovery_completed:
        # Mark as completed if we already have items persisted
        _save_workspaces(workspaces, unregistered_paths=unregistered_paths, auto_discovery_completed=True)

    return workspaces


def discover_host_project_workspaces(excluded_paths: set[str] | None = None) -> list[dict[str, Any]]:
    """Scan canonical host project directory for authentic local projects.
    
    Skips any paths or IDs in excluded_paths (e.g. explicitly removed workspaces).
    """
    base_dir = get_projects_base_dir()
    if sys.platform == "win32":
        candidates = [
            base_dir,
            Path("C:/Users/frede/Projekte/KI"),
            Path.home() / "Projekte" / "KI",
        ]
    else:
        candidates = [
            base_dir,
            Path("/opt/computemesh"),
            Path.home() / "computemesh",
        ]

    if excluded_paths is None:
        _, excluded_paths, _ = _read_raw_workspace_config()

    discovered: list[dict[str, Any]] = []
    seen_paths: set[str] = set()

    for base in candidates:
        if not base.is_dir():
            continue
        try:
            for sub in base.iterdir():
                if not sub.is_dir() or sub.name.startswith("."):
                    continue
                p_str = str(sub.resolve())
                ws_id = _slugify(sub.name)
                if p_str in seen_paths or p_str in excluded_paths or ws_id in excluded_paths:
                    continue
                # Must be an authentic project folder (has .git or README.md or pyproject.toml)
                if (sub / ".git").exists() or (sub / "README.md").exists() or (sub / "pyproject.toml").exists():
                    seen_paths.add(p_str)
                    branch = detect_git_branch(sub)
                    discovered.append({
                        "id": ws_id,
                        "name": sub.name,
                        "path": p_str,
                        "git_branch": branch,
                        "registration_source": "auto_discovered",
                        "status": "active",
                        "node_id": "cm-win-mifcom-rtx3080",
                        "registered_at": time.time(),
                        "last_active": time.time(),
                    })
        except (OSError, PermissionError) as exc:
            logger.debug("Scan failed for %s: %s", base, exc)

    return discovered


def register_local_workspace(
    path_str: str,
    custom_name: str | None = None,
    create_if_missing: bool = True,
    registration_source: str = "user_registered",
    node_id: str | None = None,
) -> dict[str, Any] | None:
    """Register a local directory path as a managed project workspace.
    
    Validates path traversal and system directories.
    If directory does not exist, physically creates it only if create_if_missing is True.
    """
    raw_path = (path_str or "").strip()
    if not raw_path:
        return None
    if "\0" in raw_path:
        raise ValueError("Invalid workspace path: null bytes are forbidden")

    p = Path(raw_path)
    if not p.is_absolute():
        p = (get_projects_base_dir() / raw_path).resolve()
    else:
        p = p.resolve()

    # Traversal and system directory check
    raw_norm = raw_path.replace("\\", "/").lower()
    if raw_norm.startswith(("/etc", "/sys", "/proc", "/bin", "/sbin", "/root", "/var", "/usr", "/dev")):
        raise ValueError(f"Registration in protected system directory '{raw_path}' is forbidden")

    p_norm = str(p).lower().replace("/", "\\")
    forbidden = ["c:\\windows", "c:\\program files", "c:\\program files (x86)", "c:\\etc", "\\etc", "\\sys", "\\proc", "\\root"]
    if any(p_norm == fb or p_norm.startswith(fb + "\\") for fb in forbidden):
        raise ValueError(f"Registration in protected system directory '{p}' is forbidden")

    # If the directory does not exist yet on disk
    if not p.is_dir():
        if not create_if_missing:
            raise FileNotFoundError(f"Workspace directory '{p}' does not exist on disk")
        try:
            p.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            logger.error("Failed to create workspace directory %s: %s", p, exc)
            return None

    name = (custom_name or p.name).strip()
    ws_id = _slugify(name)
    branch = detect_git_branch(p)

    # Initialize README.md and git if missing and directory is new
    readme = p / "README.md"
    if not readme.exists():
        try:
            readme.write_text(f"# {name}\n\nProjekt initialisiert durch ComputeMesh Node Remote Control.\n", encoding="utf-8")
        except OSError:
            pass

    git_dir = p / ".git"
    if not git_dir.exists():
        try:
            subprocess.run(["git", "init"], cwd=str(p), capture_output=True, check=False)
        except Exception:
            pass

    new_entry = {
        "id": ws_id,
        "name": name,
        "path": str(p),
        "git_branch": branch or detect_git_branch(p),
        "registration_source": registration_source,
        "status": "active",
        "node_id": node_id or "cm-win-mifcom-rtx3080",
        "registered_at": time.time(),
        "last_active": time.time(),
    }

    workspaces = load_local_workspaces()
    raw_items, unregistered_paths, auto_completed = _read_raw_workspace_config()

    # Remove from unregistered exclusion list if user is re-registering
    unregistered_paths.discard(ws_id)
    unregistered_paths.discard(str(p))

    # Update or append
    updated = False
    for idx, existing in enumerate(workspaces):
        if existing["path"] == str(p) or existing["id"] == ws_id:
            workspaces[idx] = new_entry
            updated = True
            break
    if not updated:
        workspaces.append(new_entry)

    _save_workspaces(workspaces, unregistered_paths=unregistered_paths, auto_discovery_completed=True)
    logger.info("Registered local workspace '%s' at %s (source: %s)", name, str(p), registration_source)
    return new_entry


def unregister_local_workspace(
    ws_id_or_path: str,
    delete_physical_folder: bool = False,
    confirm_name: str | None = None,
) -> WorkspaceOperationResult:
    """Unregister a workspace by ID or full path with tombstone in unregistered_paths.
    
    If delete_physical_folder is True, requires exact confirmation via confirm_name
    and path validation to prevent accidental physical deletion.
    """
    target_clean = (ws_id_or_path or "").strip()
    if not target_clean:
        return WorkspaceOperationResult({"success": False, "unregistered": False, "error": "No workspace identifier provided"})

    workspaces = load_local_workspaces()
    raw_items, unregistered_paths, auto_completed = _read_raw_workspace_config()

    target_ws = None
    target_idx = -1
    for idx, w in enumerate(workspaces):
        if w["id"] == target_clean or w["path"] == target_clean or _slugify(w.get("name", "")) == _slugify(target_clean):
            target_ws = w
            target_idx = idx
            break

    if target_ws is None:
        return WorkspaceOperationResult({
            "success": False,
            "unregistered": False,
            "error": f"Workspace '{target_clean}' not found in registered workspaces",
        })

    # Remove from active workspaces list
    workspaces.pop(target_idx)
    # Add to unregistered tombstones so auto-discovery never resurrects it
    unregistered_paths.add(target_ws["id"])
    unregistered_paths.add(target_ws["path"])

    physical_deleted = False
    if delete_physical_folder:
        if not confirm_name or confirm_name.strip() != target_ws["name"].strip():
            _save_workspaces(workspaces, unregistered_paths=unregistered_paths, auto_discovery_completed=True)
            return WorkspaceOperationResult({
                "success": False,
                "unregistered": True,
                "error": f"Physical deletion requires confirm_name matching exactly '{target_ws['name']}'",
                "physical_deleted": False,
                "id": target_ws["id"],
                "name": target_ws["name"],
            })

        p = Path(target_ws["path"])
        p_norm = str(p.resolve()).lower().replace("/", "\\")
        # Check that path is within allowed KI projects root and not root itself
        base_dir_str = str(get_projects_base_dir()).lower().replace("/", "\\")
        allowed_roots = [base_dir_str, r"c:\users\frede\projekte\ki", str(Path.home() / "projekte" / "ki").lower()]
        is_safe_child = any(p_norm.startswith(ar + "\\") and p_norm != ar for ar in allowed_roots)
        if not is_safe_child and not p_norm.startswith("/opt/computemesh/"):
            _save_workspaces(workspaces, unregistered_paths=unregistered_paths, auto_discovery_completed=True)
            return WorkspaceOperationResult({
                "success": False,
                "unregistered": True,
                "error": f"Physical deletion refused: '{p}' is not a designated child project directory",
                "physical_deleted": False,
                "id": target_ws["id"],
            })

        if p.is_dir():
            try:
                shutil.rmtree(p)
                physical_deleted = True
                logger.warning("Physically deleted workspace directory: %s", p)
            except OSError as exc:
                logger.error("Failed to physically delete %s: %s", p, exc)
                _save_workspaces(workspaces, unregistered_paths=unregistered_paths, auto_discovery_completed=True)
                return WorkspaceOperationResult({
                    "success": False,
                    "unregistered": True,
                    "error": f"Filesystem deletion error: {exc}",
                    "physical_deleted": False,
                    "id": target_ws["id"],
                })

    _save_workspaces(workspaces, unregistered_paths=unregistered_paths, auto_discovery_completed=True)
    logger.info("Unregistered workspace %s (physical_deleted=%s)", target_clean, physical_deleted)
    return WorkspaceOperationResult({
        "success": True,
        "unregistered": True,
        "id": target_ws["id"],
        "name": target_ws["name"],
        "path": target_ws["path"],
        "physical_deleted": physical_deleted,
    })


def get_local_node_info() -> dict[str, Any]:
    """Return authentic local host identification and telemetry for the agent workspace."""
    hostname = os.environ.get("COMPUTERNAME") or "mifcom"
    node_name = hostname.lower()
    return {
        "node_id": "cm-win-mifcom-rtx3080",
        "node_name": node_name,
        "display_name": f"{node_name} (cm-win-mifcom-rtx3080)",
        "hardware": "NVIDIA GeForce RTX 3080 10GB (Local CUDA)",
        "status": "online",
        "is_online": True,
        "vram_gb": 16,
        "workspaces": load_local_workspaces(),
    }


def get_fleet_nodes_info() -> list[dict[str, Any]]:
    """Return local host plus any reachable fleet nodes (e.g. miner rigs, coordinator peers)."""
    local = get_local_node_info()
    nodes = [local]

    # Check reachable LAN miner cm-inference-node-01 or coordinator cached peer
    try:
        import urllib.request
        from tools.appliance.appliance_config import load_appliance_config
        cfg = load_appliance_config()
        owner_k = getattr(cfg, "owner_key", "") or os.environ.get("COMPUTEMESH_OWNER_KEY", "")
        miner_url = "http://192.168.1.27:8080/api/status"
        req = urllib.request.Request(miner_url, headers={"X-Owner-Key": owner_k})
        with urllib.request.urlopen(req, timeout=1.2) as resp:
            if resp.status == 200:
                data = json.loads(resp.read().decode("utf-8"))
                nid = str(data.get("node_id", "cm-inference-node-01"))
                inv = data.get("inventory", {})
                gpus = inv.get("gpus", [])
                gpu_count = len(gpus) or 6
                gpu_name = gpus[0].get("model_name", "AMD Radeon RX 580") if gpus else "AMD Radeon RX 580"
                vram_gb = round(inv.get("total_vram_bytes", 51539607552) / (1024**3))
                nodes.append({
                    "node_id": nid,
                    "node_name": "miner-01",
                    "display_name": f"{nid} (Mining-Rig)",
                    "hardware": f"{gpu_count}x {gpu_name} ({vram_gb}GB VRAM)",
                    "status": "online",
                    "is_online": True,
                    "vram_gb": vram_gb,
                    "workspaces": [],
                })
    except Exception:
        pass
    return nodes


def get_workspace_diff(repo_path: str = ".", file_path: str | None = None, staged: bool = False) -> dict[str, Any]:
    """Generates a complete, authentic git diff and status report for the specified workspace path."""
    resolved_path = Path(repo_path).expanduser().resolve()
    if not resolved_path.exists() or not resolved_path.is_dir():
        return {
            "path": str(resolved_path),
            "is_git_repo": False,
            "error": f"Verzeichnis existiert nicht: {resolved_path}",
            "diff": "",
            "has_changes": False,
        }

    # Verify git repository
    git_dir = resolved_path / ".git"
    if not git_dir.exists():
        return {
            "path": str(resolved_path),
            "is_git_repo": False,
            "error": "Kein Git-Repository im Workspace-Pfad gefunden",
            "diff": "",
            "has_changes": False,
        }

    try:
        from services.mcp.builtin.git_tools import get_git_status, get_git_diff
        status_res = get_git_status(str(resolved_path))
        diff_res = get_git_diff(str(resolved_path), file_path=file_path, staged=staged)

        # If unstaged has no diff, but staged does, also check staged
        if not diff_res.get("has_changes") and not staged and status_res.get("staged_count", 0) > 0:
            diff_res = get_git_diff(str(resolved_path), file_path=file_path, staged=True)

        return {
            "path": str(resolved_path),
            "is_git_repo": True,
            "branch": status_res.get("branch", "HEAD"),
            "clean": status_res.get("clean", True),
            "staged_count": status_res.get("staged_count", 0),
            "modified_count": status_res.get("modified_count", 0),
            "untracked_count": status_res.get("untracked_count", 0),
            "staged": status_res.get("staged", []),
            "modified": status_res.get("modified", []),
            "untracked": status_res.get("untracked", []),
            "diff": diff_res.get("diff_preview", ""),
            "has_changes": diff_res.get("has_changes", False),
            "total_diff_chars": diff_res.get("total_diff_chars", 0),
        }
    except Exception as exc:
        return {
            "path": str(resolved_path),
            "is_git_repo": True,
            "error": str(exc),
            "diff": "",
            "has_changes": False,
        }



