# SPDX-License-Identifier: Apache-2.0
"""GitHub Releases, Commits, and CI/CD Workflow Runs Tools."""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from .github_client import execute_github_request
from .github_repo_tools import _resolve_owner_repo

log = logging.getLogger("computemesh.mcp.github_ci_tools")


def github_list_releases(
    repo: Optional[str] = None,
    owner: Optional[str] = None,
    limit: int = 10,
    per_page: int = 10,
) -> Dict[str, Any]:
    """Lists recent releases and git tags for a repository."""
    try:
        r_owner, r_name = _resolve_owner_repo(repo=repo, owner=owner)
    except Exception as exc:
        return {"error": str(exc), "releases": []}

    count = min(30, max(1, limit or per_page))
    resp = execute_github_request(f"/repos/{r_owner}/{r_name}/releases", params={"per_page": count})
    if not resp.get("success"):
        return {"error": resp.get("error", "Releases konnten nicht geladen werden."), "releases": []}

    raw_items = resp.get("data", [])
    if not isinstance(raw_items, list):
        return {"error": "Unerwartetes Antwortformat.", "releases": []}

    releases: List[Dict[str, Any]] = []
    for it in raw_items:
        releases.append({
            "tag_name": it.get("tag_name"),
            "name": it.get("name") or it.get("tag_name"),
            "published_at": it.get("published_at"),
            "prerelease": it.get("prerelease", False),
            "html_url": it.get("html_url"),
            "author": it.get("author", {}).get("login") if isinstance(it.get("author"), dict) else "N/A",
            "assets_count": len(it.get("assets", [])),
            "body_snippet": (it.get("body") or "")[:300].strip(),
        })

    return {
        "repository": f"{r_owner}/{r_name}",
        "total_releases": len(releases),
        "releases": releases,
    }


def github_get_latest_release(repo: Optional[str] = None, owner: Optional[str] = None) -> Dict[str, Any]:
    """Retrieves full changelog, assets, and metadata for the latest release."""
    try:
        r_owner, r_name = _resolve_owner_repo(repo=repo, owner=owner)
    except Exception as exc:
        return {"error": str(exc), "success": False}

    resp = execute_github_request(f"/repos/{r_owner}/{r_name}/releases/latest")
    if not resp.get("success"):
        return {"error": resp.get("error", "Kein Release gefunden."), "success": False}

    data = resp.get("data", {})
    assets: List[Dict[str, Any]] = []
    for a in data.get("assets", []):
        assets.append({
            "name": a.get("name"),
            "size": a.get("size", 0),
            "download_count": a.get("download_count", 0),
            "browser_download_url": a.get("browser_download_url"),
        })

    return {
        "success": True,
        "repository": f"{r_owner}/{r_name}",
        "tag_name": data.get("tag_name"),
        "name": data.get("name") or data.get("tag_name"),
        "published_at": data.get("published_at"),
        "html_url": data.get("html_url"),
        "body": data.get("body") or "",
        "assets": assets,
    }


def github_list_commits(
    repo: Optional[str] = None,
    owner: Optional[str] = None,
    sha: Optional[str] = None,
    limit: int = 20,
    per_page: int = 20,
) -> Dict[str, Any]:
    """Retrieves commit history with commit SHA, author, date, and commit message."""
    try:
        r_owner, r_name = _resolve_owner_repo(repo=repo, owner=owner)
    except Exception as exc:
        return {"error": str(exc), "commits": []}

    count = min(30, max(1, limit or per_page))
    params = {"per_page": count}
    if sha:
        params["sha"] = sha.strip()

    resp = execute_github_request(f"/repos/{r_owner}/{r_name}/commits", params=params)
    if not resp.get("success"):
        return {"error": resp.get("error", "Commits konnten nicht geladen werden."), "commits": []}

    raw_items = resp.get("data", [])
    if not isinstance(raw_items, list):
        return {"error": "Unerwartetes Antwortformat.", "commits": []}

    commits: List[Dict[str, Any]] = []
    for it in raw_items:
        c_obj = it.get("commit", {})
        commits.append({
            "sha": it.get("sha", "")[:10],
            "full_sha": it.get("sha"),
            "message": c_obj.get("message", "").strip(),
            "author": c_obj.get("author", {}).get("name") if isinstance(c_obj.get("author"), dict) else "N/A",
            "date": c_obj.get("author", {}).get("date") if isinstance(c_obj.get("author"), dict) else "",
            "html_url": it.get("html_url"),
        })

    return {
        "repository": f"{r_owner}/{r_name}",
        "total_commits": len(commits),
        "commits": commits,
    }


def github_get_workflow_runs(
    repo: Optional[str] = None,
    owner: Optional[str] = None,
    status: Optional[str] = None,
    limit: int = 10,
    per_page: int = 10,
) -> Dict[str, Any]:
    """Retrieves recent GitHub Actions CI/CD workflow runs."""
    try:
        r_owner, r_name = _resolve_owner_repo(repo=repo, owner=owner)
    except Exception as exc:
        return {"error": str(exc), "workflow_runs": []}

    count = min(30, max(1, limit or per_page))
    params = {"per_page": count}
    if status:
        params["status"] = status.strip()

    resp = execute_github_request(f"/repos/{r_owner}/{r_name}/actions/runs", params=params)
    if not resp.get("success"):
        return {"error": resp.get("error", "Workflow-Läufe konnten nicht geladen werden."), "workflow_runs": []}

    raw_items = resp.get("data", {}).get("workflow_runs", [])
    runs: List[Dict[str, Any]] = []
    for it in raw_items:
        runs.append({
            "id": it.get("id"),
            "name": it.get("name"),
            "head_branch": it.get("head_branch"),
            "status": it.get("status"),
            "conclusion": it.get("conclusion") or it.get("status"),
            "event": it.get("event"),
            "html_url": it.get("html_url"),
            "created_at": it.get("created_at"),
            "updated_at": it.get("updated_at"),
        })

    return {
        "repository": f"{r_owner}/{r_name}",
        "total_workflow_runs": len(runs),
        "workflow_runs": runs,
    }
