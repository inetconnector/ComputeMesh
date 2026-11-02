# SPDX-License-Identifier: Apache-2.0
"""Git Workspace Version Control and Diff Inspector for ComputeMesh."""

from __future__ import annotations

import logging
import os
import subprocess
from typing import Any

log = logging.getLogger("computemesh.mcp.git_tools")


def _run_git_cmd(args: list[str], repo_path: str = ".", timeout: float = 10.0) -> tuple[int, str, str]:
    try:
        proc = subprocess.run(
            ["git"] + args,
            check=False, cwd=os.path.abspath(repo_path),
            capture_output=True,
            text=True,
            timeout=timeout,
            encoding="utf-8",
            errors="replace",
        )
        return proc.returncode, proc.stdout.strip(), proc.stderr.strip()
    except Exception as exc:
        return 1, "", str(exc)


def get_git_status(repo_path: str = ".") -> dict[str, Any]:
    """Retrieves current branch and list of staged, modified, and untracked files."""
    _code_br, current_branch, _ = _run_git_cmd(["branch", "--show-current"], repo_path)
    code_st, raw_status, err = _run_git_cmd(["status", "--porcelain=v1"], repo_path)

    if code_st != 0:
        return {"error": f"Kein Git-Repository oder Fehler: {err}", "is_git_repo": False}

    staged: list[str] = []
    modified: list[str] = []
    untracked: list[str] = []

    for line in raw_status.splitlines():
        if len(line) < 3:
            continue
        idx_status = line[0]
        work_status = line[1]
        fname = line[3:].strip()

        if idx_status in ("M", "A", "D", "R"):
            staged.append(fname)
        if work_status in ("M", "D"):
            modified.append(fname)
        if idx_status == "?" and work_status == "?":
            untracked.append(fname)

    return {
        "is_git_repo": True,
        "branch": current_branch or "HEAD (detached)",
        "staged_count": len(staged),
        "modified_count": len(modified),
        "untracked_count": len(untracked),
        "staged": staged,
        "modified": modified,
        "untracked": untracked,
        "clean": len(staged) == 0 and len(modified) == 0 and len(untracked) == 0,
    }


def get_git_diff(repo_path: str = ".", file_path: str | None = None, staged: bool = False) -> dict[str, Any]:
    """Generates unified diff of workspace changes for whole repo or specific file."""
    cmd = ["diff"]
    if staged:
        cmd.append("--staged")
    if file_path:
        cmd.extend(["--", file_path])

    code, raw_diff, err = _run_git_cmd(cmd, repo_path)
    if code != 0:
        return {"error": f"Git Diff Fehler: {err}", "diff": ""}

    return {
        "staged": staged,
        "file_path": file_path,
        "has_changes": bool(raw_diff),
        "diff_preview": raw_diff[:8000] if len(raw_diff) > 8000 else raw_diff,
        "total_diff_chars": len(raw_diff),
    }


def get_git_log(repo_path: str = ".", max_count: int = 10) -> dict[str, Any]:
    """Retrieves recent commit log history."""
    fmt = "%H|%an|%ad|%s"
    code, raw_log, err = _run_git_cmd(["log", f"-n{max_count}", f"--pretty=format:{fmt}", "--date=short"], repo_path)
    if code != 0:
        return {"error": f"Git Log Fehler: {err}", "commits": []}

    commits: list[dict[str, str]] = []
    for line in raw_log.splitlines():
        parts = line.split("|", 3)
        if len(parts) == 4:
            commits.append({
                "hash": parts[0][:8],
                "full_hash": parts[0],
                "author": parts[1],
                "date": parts[2],
                "subject": parts[3],
            })

    return {
        "total_commits_fetched": len(commits),
        "commits": commits,
    }
