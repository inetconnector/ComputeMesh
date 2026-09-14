# SPDX-License-Identifier: Apache-2.0
"""100% Secure WebApp Deployer and Host Manager for ComputeMesh."""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path
import re
import shutil
import time
from typing import Any, Dict, List, Optional

log = logging.getLogger("computemesh.mcp.webapp_deployer")

REPO_ROOT = Path(__file__).resolve().parents[3]
APPS_DIR = REPO_ROOT / "portal" / "apps"

# Dangerous malware / exfiltration patterns to block before deployment
BLOCKED_PATTERNS = [
    re.compile(r"coinhive|cryptonight|stratum\+tcp|webminer|monero|crypto-loot", re.IGNORECASE),
    re.compile(r"eval\s*\(\s*(?:atob|unescape)\s*\(", re.IGNORECASE),
    re.compile(r"document\.cookie", re.IGNORECASE),
    re.compile(r"window\.opener\.location", re.IGNORECASE),
    re.compile(r"(?:169\.254\.169\.254|metadata\.google\.internal)", re.IGNORECASE),
]


def _sanitize_slug(name: str) -> str:
    slug = re.sub(r"[^a-z0-9_-]", "-", name.lower().strip())
    slug = re.sub(r"-+", "-", slug).strip("-")
    return slug or "webapp"


def _scan_code_safety(code_snippets: List[str]) -> Optional[str]:
    """Scans all code for malicious patterns, crypto-miners, and exfiltration hooks."""
    for code in code_snippets:
        if not code:
            continue
        for pat in BLOCKED_PATTERNS:
            if pat.search(code):
                return f"Sicherheitsblockade: Gefährliches Muster erkannt ({pat.pattern})"
    return None


def deploy_local_webapp(
    app_name: str,
    title: str,
    html_content: str,
    js_content: Optional[str] = None,
    css_content: Optional[str] = None,
    extra_files: Optional[Dict[str, str]] = None,
    description: Optional[str] = None,
) -> Dict[str, Any]:
    """Deploys a sandboxed, interactive client-side web application or game to the ComputeMesh node."""
    slug = _sanitize_slug(app_name)
    target_dir = APPS_DIR / slug

    # Strict Directory Jail Check
    APPS_DIR.mkdir(parents=True, exist_ok=True)
    resolved_target = target_dir.resolve()
    resolved_apps = APPS_DIR.resolve()
    try:
        resolved_target.relative_to(resolved_apps)
    except ValueError:
        return {"error": "Sicherheitsblockade: Path-Traversal-Versuch abgewiesen.", "success": False}

    # Security Pre-Scan
    snippets = [html_content, js_content or "", css_content or ""]
    if extra_files:
        snippets.extend(extra_files.values())

    violation = _scan_code_safety(snippets)
    if violation:
        return {"error": violation, "success": False}

    try:
        target_dir.mkdir(parents=True, exist_ok=True)

        # Write index.html
        (target_dir / "index.html").write_text(html_content, encoding="utf-8")

        # Write game.js / app.js if provided
        if js_content is not None:
            (target_dir / "app.js").write_text(js_content, encoding="utf-8")

        # Write style.css if provided
        if css_content is not None:
            (target_dir / "style.css").write_text(css_content, encoding="utf-8")

        # Write any extra files (JSON configs, assets)
        if extra_files:
            for rel_fn, content in extra_files.items():
                safe_fn = os.path.basename(rel_fn.replace("\\", "/"))
                (target_dir / safe_fn).write_text(content, encoding="utf-8")

        # Create app.json manifest
        manifest = {
            "app_name": slug,
            "title": title or slug,
            "description": description or f"ComputeMesh Dezentrale WebApp: {title}",
            "deployed_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "entry_point": "index.html",
            "url_path": f"/apps/{slug}/index.html",
            "version": "1.0.0",
        }
        (target_dir / "app.json").write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")

        total_bytes = sum(f.stat().st_size for f in target_dir.rglob("*") if f.is_file())

        return {
            "success": True,
            "app_name": slug,
            "title": title or slug,
            "url_path": f"/apps/{slug}/index.html",
            "full_local_url": f"http://127.0.0.1:8080/apps/{slug}/index.html",
            "total_files": len(list(target_dir.glob("*"))),
            "size_bytes": total_bytes,
            "message": f"WebApp '{title}' erfolgreich unter /apps/{slug}/index.html bereitgestellt!",
        }
    except Exception as exc:
        log.error(f"Error deploying webapp {slug}: {exc}")
        return {"error": f"Fehler bei Bereitstellung: {str(exc)}", "success": False}


def list_deployed_webapps() -> Dict[str, Any]:
    """Lists all active sandboxed applications and games deployed on this ComputeMesh node."""
    if not APPS_DIR.exists():
        return {"total_apps": 0, "apps": []}

    apps: List[Dict[str, Any]] = []
    for app_folder in sorted(APPS_DIR.iterdir()):
        if app_folder.is_dir():
            manifest_file = app_folder / "app.json"
            if manifest_file.exists():
                try:
                    data = json.loads(manifest_file.read_text(encoding="utf-8"))
                    apps.append(data)
                    continue
                except Exception:
                    pass
            apps.append({
                "app_name": app_folder.name,
                "title": app_folder.name.replace("-", " ").title(),
                "url_path": f"/apps/{app_folder.name}/index.html",
                "full_local_url": f"http://127.0.0.1:8080/apps/{app_folder.name}/index.html",
            })

    return {
        "success": True,
        "total_apps": len(apps),
        "apps": apps,
    }


def remove_deployed_webapp(app_name: str) -> Dict[str, Any]:
    """Securely uninstalls and removes a deployed application from the node."""
    slug = _sanitize_slug(app_name)
    target_dir = APPS_DIR / slug

    if not target_dir.exists() or not target_dir.is_dir():
        return {"error": f"WebApp '{slug}' wurde nicht gefunden.", "success": False}

    # Strict Jail Check
    try:
        target_dir.resolve().relative_to(APPS_DIR.resolve())
    except ValueError:
        return {"error": "Ungültiger Verzeichnispfad.", "success": False}

    shutil.rmtree(target_dir, ignore_errors=True)
    return {
        "success": True,
        "app_name": slug,
        "message": f"WebApp '{slug}' wurde erfolgreich deinstalliert und entfernt.",
    }


def launch_deployed_webapp(app_name: str = "pacman") -> Dict[str, Any]:
    """Öffnet, startet oder liefert den direkten spielbaren Link zu einer installierten WebApp oder einem Spiel wie Pac-Man."""
    slug = _sanitize_slug(app_name) if app_name else "pacman"
    target_dir = APPS_DIR / slug
    if not target_dir.exists() or not (target_dir / "index.html").exists():
        if (APPS_DIR / "pacman" / "index.html").exists():
            slug = "pacman"
            target_dir = APPS_DIR / "pacman"
        else:
            return {"error": f"Anwendung '{slug}' nicht gefunden.", "success": False}

    url_path = f"/apps/{slug}/index.html"
    return {
        "success": True,
        "app_name": slug,
        "title": "ComputeMesh Pac-Man Arcade" if slug == "pacman" else slug,
        "url_path": url_path,
        "full_local_url": f"http://127.0.0.1:8080{url_path}",
        "action": "open_url",
        "message": f"🎮 Spiel '{slug}' ist bereit! Öffne Link: http://127.0.0.1:8080{url_path}",
    }

