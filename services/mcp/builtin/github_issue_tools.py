# SPDX-License-Identifier: Apache-2.0
"""GitHub Issues and Comments Management Tools."""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from .github_client import execute_github_request
from .github_repo_tools import _resolve_owner_repo

log = logging.getLogger("computemesh.mcp.github_issue_tools")


def github_list_issues(
    repo: Optional[str] = None,
    owner: Optional[str] = None,
    state: str = "open",
    labels: Optional[str] = None,
    limit: int = 20,
    per_page: int = 20,
) -> Dict[str, Any]:
    """Lists issues for a GitHub repository with status, labels, and comment counts."""
    try:
        r_owner, r_name = _resolve_owner_repo(repo=repo, owner=owner)
    except Exception as exc:
        return {"error": str(exc), "issues": []}

    count = min(30, max(1, limit or per_page))
    params = {
        "state": state,
        "per_page": count,
    }
    if labels:
        params["labels"] = labels.strip()

    resp = execute_github_request(f"/repos/{r_owner}/{r_name}/issues", params=params)
    if not resp.get("success"):
        return {"error": resp.get("error", "Issues konnten nicht geladen werden."), "issues": []}

    raw_items = resp.get("data", [])
    if not isinstance(raw_items, list):
        return {"error": "Unerwartetes Antwortformat.", "issues": []}

    issues: List[Dict[str, Any]] = []
    for it in raw_items:
        if "pull_request" in it:
            continue
        issues.append({
            "number": it.get("number"),
            "title": it.get("title"),
            "state": it.get("state"),
            "author": it.get("user", {}).get("login") if isinstance(it.get("user"), dict) else "N/A",
            "comments_count": it.get("comments", 0),
            "labels": [lbl.get("name") for lbl in it.get("labels", []) if isinstance(lbl, dict)],
            "html_url": it.get("html_url"),
            "created_at": it.get("created_at"),
            "body_snippet": (it.get("body") or "")[:200].strip(),
        })

    return {
        "repository": f"{r_owner}/{r_name}",
        "state": state,
        "total_issues": len(issues),
        "issues": issues,
    }


def github_get_issue(issue_number: int, repo: Optional[str] = None, owner: Optional[str] = None) -> Dict[str, Any]:
    """Retrieves full body, comments, and metadata for a specific GitHub issue."""
    try:
        r_owner, r_name = _resolve_owner_repo(repo=repo, owner=owner)
    except Exception as exc:
        return {"error": str(exc), "success": False}

    resp = execute_github_request(f"/repos/{r_owner}/{r_name}/issues/{issue_number}")
    if not resp.get("success"):
        return {"error": resp.get("error", f"Issue #{issue_number} nicht gefunden."), "success": False}

    data = resp.get("data", {})
    comments: List[Dict[str, Any]] = []
    c_resp = execute_github_request(f"/repos/{r_owner}/{r_name}/issues/{issue_number}/comments", params={"per_page": 15})
    if c_resp.get("success") and isinstance(c_resp.get("data"), list):
        for c in c_resp["data"]:
            comments.append({
                "id": c.get("id"),
                "author": c.get("user", {}).get("login") if isinstance(c.get("user"), dict) else "N/A",
                "body": c.get("body", ""),
                "created_at": c.get("created_at"),
            })

    return {
        "success": True,
        "repository": f"{r_owner}/{r_name}",
        "issue_number": issue_number,
        "title": data.get("title"),
        "state": data.get("state"),
        "author": data.get("user", {}).get("login") if isinstance(data.get("user"), dict) else "N/A",
        "html_url": data.get("html_url"),
        "created_at": data.get("created_at"),
        "labels": [lbl.get("name") for lbl in data.get("labels", []) if isinstance(lbl, dict)],
        "body": data.get("body") or "",
        "comments_count": len(comments),
        "comments": comments,
    }


def github_create_issue(
    title: str,
    repo: Optional[str] = None,
    owner: Optional[str] = None,
    body: str = "",
    labels: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """Creates a new issue in a GitHub repository."""
    try:
        r_owner, r_name = _resolve_owner_repo(repo=repo, owner=owner)
    except Exception as exc:
        return {"error": str(exc), "success": False}

    payload: Dict[str, Any] = {"title": title.strip(), "body": body.strip()}
    if labels:
        payload["labels"] = labels

    resp = execute_github_request(
        f"/repos/{r_owner}/{r_name}/issues",
        method="POST",
        json_body=payload,
    )
    if not resp.get("success"):
        return {"error": resp.get("error", "Issue-Erstellung fehlgeschlagen (Token-Rechte prüfen)."), "success": False}

    data = resp.get("data", {})
    return {
        "success": True,
        "repository": f"{r_owner}/{r_name}",
        "issue_number": data.get("number"),
        "title": data.get("title"),
        "html_url": data.get("html_url"),
    }


def github_add_issue_comment(
    issue_number: int,
    body: str,
    repo: Optional[str] = None,
    owner: Optional[str] = None,
) -> Dict[str, Any]:
    """Adds a new comment to a GitHub issue or pull request."""
    try:
        r_owner, r_name = _resolve_owner_repo(repo=repo, owner=owner)
    except Exception as exc:
        return {"error": str(exc), "success": False}

    resp = execute_github_request(
        f"/repos/{r_owner}/{r_name}/issues/{issue_number}/comments",
        method="POST",
        json_body={"body": body.strip()},
    )
    if not resp.get("success"):
        return {"error": resp.get("error", "Kommentar konnte nicht gesendet werden."), "success": False}

    data = resp.get("data", {})
    return {
        "success": True,
        "repository": f"{r_owner}/{r_name}",
        "issue_number": issue_number,
        "comment_id": data.get("id"),
        "html_url": data.get("html_url"),
    }
