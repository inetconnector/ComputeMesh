# SPDX-License-Identifier: Apache-2.0
"""GitHub Pull Requests, Reviews, and Diff Inspection Tools."""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from .github_client import execute_github_request
from .github_repo_tools import _resolve_owner_repo

log = logging.getLogger("computemesh.mcp.github_pr_tools")


def github_list_pull_requests(
    repo: Optional[str] = None,
    owner: Optional[str] = None,
    state: str = "open",
    limit: int = 20,
    per_page: int = 20,
) -> Dict[str, Any]:
    """Lists pull requests for a repository with branch info, review status, and draft status."""
    try:
        r_owner, r_name = _resolve_owner_repo(repo=repo, owner=owner)
    except Exception as exc:
        return {"error": str(exc), "pull_requests": []}

    count = min(30, max(1, limit or per_page))
    resp = execute_github_request(
        f"/repos/{r_owner}/{r_name}/pulls",
        params={"state": state, "per_page": count},
    )
    if not resp.get("success"):
        return {"error": resp.get("error", "Pull Requests konnten nicht geladen werden."), "pull_requests": []}

    raw_items = resp.get("data", [])
    if not isinstance(raw_items, list):
        return {"error": "Unerwartetes Antwortformat.", "pull_requests": []}

    prs: List[Dict[str, Any]] = []
    for it in raw_items:
        prs.append({
            "number": it.get("number"),
            "title": it.get("title"),
            "state": it.get("state"),
            "draft": it.get("draft", False),
            "author": it.get("user", {}).get("login") if isinstance(it.get("user"), dict) else "N/A",
            "head_branch": it.get("head", {}).get("ref") if isinstance(it.get("head"), dict) else "N/A",
            "base_branch": it.get("base", {}).get("ref") if isinstance(it.get("base"), dict) else "N/A",
            "html_url": it.get("html_url"),
            "created_at": it.get("created_at"),
            "updated_at": it.get("updated_at"),
        })

    return {
        "repository": f"{r_owner}/{r_name}",
        "state": state,
        "total_prs": len(prs),
        "pull_requests": prs,
    }


def github_get_pull_request(pull_number: int, repo: Optional[str] = None, owner: Optional[str] = None) -> Dict[str, Any]:
    """Retrieves full details of a pull request including mergeable state, commits count, and stats."""
    try:
        r_owner, r_name = _resolve_owner_repo(repo=repo, owner=owner)
    except Exception as exc:
        return {"error": str(exc), "success": False}

    resp = execute_github_request(f"/repos/{r_owner}/{r_name}/pulls/{pull_number}")
    if not resp.get("success"):
        return {"error": resp.get("error", f"Pull Request #{pull_number} nicht gefunden."), "success": False}

    data = resp.get("data", {})
    return {
        "success": True,
        "repository": f"{r_owner}/{r_name}",
        "pull_number": pull_number,
        "title": data.get("title"),
        "state": data.get("state"),
        "draft": data.get("draft", False),
        "merged": data.get("merged", False),
        "mergeable": data.get("mergeable"),
        "author": data.get("user", {}).get("login") if isinstance(data.get("user"), dict) else "N/A",
        "head_branch": data.get("head", {}).get("ref") if isinstance(data.get("head"), dict) else "N/A",
        "base_branch": data.get("base", {}).get("ref") if isinstance(data.get("base"), dict) else "N/A",
        "commits": data.get("commits", 0),
        "additions": data.get("additions", 0),
        "deletions": data.get("deletions", 0),
        "changed_files": data.get("changed_files", 0),
        "html_url": data.get("html_url"),
        "body": data.get("body") or "",
    }


def github_get_pull_request_diff(pull_number: int, repo: Optional[str] = None, owner: Optional[str] = None) -> Dict[str, Any]:
    """Retrieves the unified diff of a pull request."""
    try:
        r_owner, r_name = _resolve_owner_repo(repo=repo, owner=owner)
    except Exception as exc:
        return {"error": str(exc), "success": False}

    resp = execute_github_request(
        f"/repos/{r_owner}/{r_name}/pulls/{pull_number}",
        accept_header="application/vnd.github.v3.diff",
    )
    if not resp.get("success"):
        return {"error": resp.get("error", "Diff konnte nicht geladen werden."), "success": False}

    diff_text = str(resp.get("data", ""))
    return {
        "success": True,
        "repository": f"{r_owner}/{r_name}",
        "pull_number": pull_number,
        "diff_chars": len(diff_text),
        "diff": diff_text[:80000] if len(diff_text) > 80000 else diff_text,
    }


def github_get_pull_request_files(pull_number: int, repo: Optional[str] = None, owner: Optional[str] = None) -> Dict[str, Any]:
    """Lists files changed in a pull request with additions, deletions, and status."""
    try:
        r_owner, r_name = _resolve_owner_repo(repo=repo, owner=owner)
    except Exception as exc:
        return {"error": str(exc), "files": []}

    resp = execute_github_request(f"/repos/{r_owner}/{r_name}/pulls/{pull_number}/files", params={"per_page": 50})
    if not resp.get("success"):
        return {"error": resp.get("error", "Dateiliste konnte nicht geladen werden."), "files": []}

    raw_files = resp.get("data", [])
    files: List[Dict[str, Any]] = []
    adds = 0
    dels = 0
    if isinstance(raw_files, list):
        for f in raw_files:
            fa = f.get("additions", 0)
            fd = f.get("deletions", 0)
            adds += fa
            dels += fd
            files.append({
                "filename": f.get("filename"),
                "status": f.get("status"),
                "additions": fa,
                "deletions": fd,
                "changes": f.get("changes", fa + fd),
                "patch_snippet": (f.get("patch") or "")[:500].strip(),
            })

    return {
        "repository": f"{r_owner}/{r_name}",
        "pull_number": pull_number,
        "total_files": len(files),
        "additions": adds,
        "deletions": dels,
        "files": files,
    }
