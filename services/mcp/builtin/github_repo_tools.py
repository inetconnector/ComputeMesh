# SPDX-License-Identifier: Apache-2.0
"""GitHub Repository, Directory Tree, and Code Search Tools."""

from __future__ import annotations

import base64
import logging
from typing import Any, Dict, List, Optional

from .github_client import execute_github_request

log = logging.getLogger("computemesh.mcp.github_repo_tools")


def _resolve_owner_repo(repo: Optional[str] = None, owner: Optional[str] = None) -> tuple[str, str]:
    if owner and repo:
        if "/" in repo:
            parts = repo.strip().strip("/").split("/", 1)
            return parts[0].strip(), parts[1].strip()
        return owner.strip(), repo.strip()
    full = (repo or owner or "").strip().strip("/")
    if "/" not in full:
        raise ValueError(f"Ungültiges Repository-Format '{full}'. Erwartet: 'owner/repo'.")
    parts = full.split("/", 1)
    return parts[0].strip(), parts[1].strip()


def github_get_repo(repo: Optional[str] = None, owner: Optional[str] = None) -> Dict[str, Any]:
    """Retrieves full repository metadata, stars, forks, language, topics, and default branch."""
    try:
        r_owner, r_name = _resolve_owner_repo(repo=repo, owner=owner)
    except Exception as exc:
        return {"error": str(exc), "success": False}

    resp = execute_github_request(f"/repos/{r_owner}/{r_name}")
    if not resp.get("success"):
        return {"error": resp.get("error", "Repository nicht gefunden."), "success": False}

    data = resp.get("data", {})
    return {
        "success": True,
        "full_name": data.get("full_name", f"{r_owner}/{r_name}"),
        "description": data.get("description") or "",
        "html_url": data.get("html_url", f"https://github.com/{r_owner}/{r_name}"),
        "stars": data.get("stargazers_count", 0),
        "forks": data.get("forks_count", 0),
        "watchers": data.get("watchers_count", 0),
        "open_issues": data.get("open_issues_count", 0),
        "default_branch": data.get("default_branch", "main"),
        "language": data.get("language") or "N/A",
        "topics": data.get("topics", []),
        "license": data.get("license", {}).get("spdx_id") or (data.get("license", {}).get("name") if isinstance(data.get("license"), dict) else data.get("license")),
        "is_private": data.get("private", False),
        "updated_at": data.get("updated_at", ""),
    }


def github_search_repositories(query: str, sort: str = "stars", limit: int = 10, per_page: int = 10) -> Dict[str, Any]:
    """Searches GitHub repositories by keyword, topic, or language."""
    q_str = str(query or "").strip()
    if not q_str:
        return {"error": "Suchbegriff darf nicht leer sein.", "repositories": []}

    count = min(30, max(1, limit or per_page))
    resp = execute_github_request("/search/repositories", params={"q": q_str, "sort": sort, "per_page": count})
    if not resp.get("success"):
        return {"error": resp.get("error", "Suche fehlgeschlagen."), "repositories": []}

    items = resp.get("data", {}).get("items", [])
    repos: List[Dict[str, Any]] = []
    for it in items:
        repos.append({
            "full_name": it.get("full_name"),
            "description": it.get("description") or "",
            "html_url": it.get("html_url"),
            "stars": it.get("stargazers_count", 0),
            "forks": it.get("forks_count", 0),
            "language": it.get("language") or "N/A",
            "updated_at": it.get("updated_at", ""),
        })

    return {
        "query": q_str,
        "total_count": resp.get("data", {}).get("total_count", len(repos)),
        "repositories": repos,
    }


def github_get_file_contents(path: str, repo: Optional[str] = None, owner: Optional[str] = None, ref: Optional[str] = None) -> Dict[str, Any]:
    """Fetches and decodes the raw text content of a file directly from a GitHub repository."""
    try:
        r_owner, r_name = _resolve_owner_repo(repo=repo, owner=owner)
    except Exception as exc:
        return {"error": str(exc), "success": False}

    clean_path = path.strip().lstrip("/")
    params = {"ref": ref} if ref else None
    resp = execute_github_request(f"/repos/{r_owner}/{r_name}/contents/{clean_path}", params=params)

    if not resp.get("success"):
        return {"error": resp.get("error", f"Datei '{path}' nicht gefunden."), "success": False}

    data = resp.get("data", {})
    if isinstance(data, list):
        return {
            "is_directory": True,
            "path": clean_path,
            "total_entries": len(data),
            "entries": [{"name": e.get("name"), "type": e.get("type"), "size": e.get("size")} for e in data],
        }

    encoding = data.get("encoding", "")
    content_raw = data.get("content", "")
    if encoding == "base64" and content_raw:
        try:
            decoded_text = base64.b64decode(content_raw).decode("utf-8", errors="replace")
        except Exception:
            decoded_text = content_raw
    else:
        decoded_text = content_raw

    return {
        "success": True,
        "repo": f"{r_owner}/{r_name}",
        "name": data.get("name", clean_path.split("/")[-1]),
        "path": clean_path,
        "size": data.get("size", 0),
        "sha": data.get("sha", ""),
        "html_url": data.get("html_url", ""),
        "content": decoded_text,
    }


def github_list_repo_tree(path: str = "", repo: Optional[str] = None, owner: Optional[str] = None, ref: Optional[str] = None) -> Dict[str, Any]:
    """Lists files and folders inside a GitHub repository directory."""
    return github_get_file_contents(path=path, repo=repo, owner=owner, ref=ref)


def github_search_code(query: str, repo: Optional[str] = None, owner: Optional[str] = None, limit: int = 10, per_page: int = 10) -> Dict[str, Any]:
    """Searches source code across GitHub repositories using GitHub Code Search."""
    q_str = str(query or "").strip()
    if owner and repo:
        q_str += f" repo:{owner}/{repo}"
    elif repo:
        q_str += f" repo:{repo.strip()}"

    count = min(30, max(1, limit or per_page))
    resp = execute_github_request("/search/code", params={"q": q_str, "per_page": count})
    if not resp.get("success"):
        return {"error": resp.get("error", "Code-Suche fehlgeschlagen."), "matches": []}

    items = resp.get("data", {}).get("items", [])
    results: List[Dict[str, Any]] = []
    for it in items:
        results.append({
            "name": it.get("name"),
            "path": it.get("path"),
            "repo": it.get("repository", {}).get("full_name"),
            "html_url": it.get("html_url"),
            "sha": it.get("sha"),
        })

    return {
        "query": query,
        "total_count": resp.get("data", {}).get("total_count", len(results)),
        "matches": results,
    }
