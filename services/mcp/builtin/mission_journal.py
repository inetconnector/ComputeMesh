# SPDX-License-Identifier: Apache-2.0
"""Structured Mission Journal and Lifecycle Checkpoint Engine."""

from __future__ import annotations

import json
import logging
import os
import time
import uuid
from typing import Any, Dict, List, Optional

log = logging.getLogger("computemesh.mcp.mission_journal")
MISSIONS_DIR_NAME = os.path.join(".computemesh", "missions")


def _get_missions_dir(workspace_root: Optional[str] = None) -> str:
    root = os.path.abspath(workspace_root or ".")
    m_dir = os.path.join(root, MISSIONS_DIR_NAME)
    os.makedirs(m_dir, exist_ok=True)
    return m_dir


def mission_start(
    objective: str,
    constraints: Optional[List[str]] = None,
    success_criteria: Optional[List[str]] = None,
    workspace_root: Optional[str] = None,
) -> Dict[str, Any]:
    """Starts and persists a structured agent mission journal."""
    clean_obj = str(objective or "").strip()
    if not clean_obj:
        return {"error": "Ziel (Objective) darf nicht leer sein.", "success": False}

    root = os.path.abspath(workspace_root or ".")
    m_id = f"mission_{int(time.time())}_{uuid.uuid4().hex[:6]}"
    m_path = os.path.join(_get_missions_dir(root), f"{m_id}.json")

    mission_data = {
        "mission_id": m_id,
        "objective": clean_obj,
        "status": "in_progress",
        "constraints": constraints or [],
        "success_criteria": success_criteria or [],
        "started_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "updated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "steps": [
            {
                "step_index": 1,
                "phase": "init",
                "action": "Mission initialisiert",
                "evidence": f"Objective: {clean_obj[:100]}",
                "status": "done",
                "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            }
        ],
        "postcondition_results": [],
    }

    with open(m_path, "w", encoding="utf-8") as f:
        json.dump(mission_data, f, indent=2)

    return {
        "success": True,
        "mission_id": m_id,
        "objective": clean_obj,
        "status": "in_progress",
    }


def mission_log_step(
    mission_id: str,
    phase: str,
    action: str,
    evidence: str = "",
    status: str = "done",
    workspace_root: Optional[str] = None,
) -> Dict[str, Any]:
    """Appends an execution step or evidence checkpoint to the mission journal."""
    root = os.path.abspath(workspace_root or ".")
    m_path = os.path.join(_get_missions_dir(root), f"{mission_id}.json")
    if not os.path.exists(m_path):
        return {"error": f"Mission '{mission_id}' nicht gefunden.", "success": False}

    with open(m_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    step_idx = len(data.get("steps", [])) + 1
    new_step = {
        "step_index": step_idx,
        "phase": phase,
        "action": action,
        "evidence": evidence[:2000],
        "status": status,
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }
    data["steps"].append(new_step)
    data["updated_at"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    if status == "failed":
        data["status"] = "blocked"

    with open(m_path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)

    return {"success": True, "mission_id": mission_id, "step_index": step_idx}


def mission_verify_postconditions(
    mission_id: str,
    checks: List[Dict[str, Any]],
    workspace_root: Optional[str] = None,
) -> Dict[str, Any]:
    """Validates mission completion against success criteria."""
    root = os.path.abspath(workspace_root or ".")
    m_path = os.path.join(_get_missions_dir(root), f"{mission_id}.json")
    if not os.path.exists(m_path):
        return {"error": f"Mission '{mission_id}' nicht gefunden.", "success": False}

    with open(m_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    all_passed = True
    results = []
    for c in checks:
        passed = bool(c.get("passed", False))
        if not passed:
            all_passed = False
        results.append({
            "name": c.get("name", "Kriterium"),
            "passed": passed,
            "details": c.get("details", ""),
        })

    data["postcondition_results"] = results
    data["status"] = "completed" if all_passed else "verification_failed"
    data["updated_at"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())

    with open(m_path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)

    return {
        "success": True,
        "mission_id": mission_id,
        "all_passed": all_passed,
        "results": results,
    }


def mission_get_summary(mission_id: str, workspace_root: Optional[str] = None) -> Dict[str, Any]:
    """Retrieves full journal history and completion state for a mission."""
    root = os.path.abspath(workspace_root or ".")
    m_path = os.path.join(_get_missions_dir(root), f"{mission_id}.json")
    if not os.path.exists(m_path):
        return {"error": f"Mission '{mission_id}' nicht gefunden.", "success": False}

    with open(m_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    return {"success": True, "mission": data}
