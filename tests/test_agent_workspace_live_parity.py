# SPDX-License-Identifier: Apache-2.0
"""Automated parity and anti-dummy verification for ComputeMesh Agent Workspace (Codex Remote Control).

Enforces Rule #7: Strict prohibition of stubs, mocks, and hardcoded fake data.
Verifies authentic host discovery on mifcoms, dynamic model loading, and neutral dark aesthetic.
"""
from __future__ import annotations

import os
from pathlib import Path
import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
PORTAL_AGENT_HTML = REPO_ROOT / "portal" / "agent.html"
NEUTRAL_THEME_CSS = REPO_ROOT / "portal" / "webui" / "neutral-theme.css"
ANDROID_THEME_CSS = REPO_ROOT / "apps" / "android" / "app" / "src" / "main" / "assets" / "webui" / "neutral-theme.css"


def test_agent_html_zero_dummies():
    """Verify portal/agent.html contains zero fake mocks, fake models, or hardcoded chats."""
    assert PORTAL_AGENT_HTML.is_file(), f"Missing {PORTAL_AGENT_HTML}"
    content = PORTAL_AGENT_HTML.read_text(encoding="utf-8")

    forbidden_terms = [
        "luna",
        "Luna",
        "GPT-5.6",
        "Der test unten soll vor jeder liveschaltung",
        "ActivityLauncher",
        "Zeitungskiosk",
        "09bb69b253540e6482d66521fb1a19844d01ec2d",
    ]
    for term in forbidden_terms:
        assert term not in content, f"Forbidden dummy term '{term}' found in portal/agent.html"


def test_agent_html_authentic_bindings():
    """Verify agent.html binds to the real node mifcoms and authentic APIs."""
    content = PORTAL_AGENT_HTML.read_text(encoding="utf-8")

    # Node references
    assert "cm-win-mifcom-rtx3080" in content, "Missing active node ID cm-win-mifcom-rtx3080"
    assert "mifcom" in content.lower(), "Missing host name mifcom in agent.html"

    # Dynamic API calls
    assert "loadFleetAndWorkspaces" in content, "Missing loadFleetAndWorkspaces call"
    assert "loadModels" in content, "Missing dynamic loadModels call"
    assert "/v1/models" in content or "/api/v1/models" in content, "Missing /v1/models endpoint query"
    assert "/v1/fleet/workspaces" in content or "/api/v1/fleet/workspaces" in content, "Missing fleet workspaces query"
    assert "filterWorkspaces" in content, "Missing workspace search filter function"


def test_workspace_manager_host_discovery():
    """Verify workspace_manager discovers authentic local projects on the host machine."""
    from tools.appliance.workspace_manager import (
        discover_host_project_workspaces,
        get_local_node_info,
        load_local_workspaces,
    )

    discovered = discover_host_project_workspaces()
    assert isinstance(discovered, list)
    assert len(discovered) > 0, "Host project discovery returned no workspaces"

    # Verify ComputeMesh-ControlPlane is discovered
    ws_paths = [w.get("path", "") for w in discovered]
    assert any("ComputeMesh" in p for p in ws_paths), "ComputeMesh project was not discovered"

    # Verify node info
    node_info = get_local_node_info()
    assert node_info["node_id"] == "cm-win-mifcom-rtx3080"
    assert "mifcom" in node_info["node_name"].lower()
    assert "RTX 3080" in node_info["hardware"]
    assert node_info["status"] == "online"
    assert len(node_info["workspaces"]) > 0


def test_neutral_theme_no_blue_outlines():
    """Verify neutral theme CSS eliminates loud blue borders and rings on dialogs and popovers."""
    assert NEUTRAL_THEME_CSS.is_file(), f"Missing {NEUTRAL_THEME_CSS}"
    assert ANDROID_THEME_CSS.is_file(), f"Missing {ANDROID_THEME_CSS}"

    for css_path in (NEUTRAL_THEME_CSS, ANDROID_THEME_CSS):
        css_text = css_path.read_text(encoding="utf-8")
        assert "--tw-ring-color: transparent !important" in css_text
        assert "border-color: rgba(255, 255, 255, 0.12) !important" in css_text


def test_workspace_physical_creation_and_isolation():
    from tools.appliance.workspace_manager import register_local_workspace, unregister_local_workspace, discover_host_project_workspaces
    import shutil
    from pathlib import Path

    test_ws_name = "TestPhysicalCreation_AutoTest"
    ws = register_local_workspace(test_ws_name)
    assert ws is not None
    assert ws["name"] == test_ws_name
    ws_path = Path(ws["path"])
    try:
        assert ws_path.is_dir(), "Physical directory must exist on disk"
        assert (ws_path / "README.md").is_file(), "README.md must be generated"
        assert (ws_path / ".git").is_dir(), "git repository must be initialized"
    finally:
        unregister_local_workspace(ws["id"])
        if ws_path.is_dir():
            shutil.rmtree(ws_path, ignore_errors=True)

    # Verify discovery isolates to KI canonical projects only
    discovered = discover_host_project_workspaces()
    discovered_names = [d["name"] for d in discovered]
    assert "ActivityLauncher" not in discovered_names, "Legacy non-KI directories must never be auto-discovered"
    assert "Zeitungskiosk" not in discovered_names, "Legacy non-KI directories must never be auto-discovered"
    assert "SpotifyPlaylistWebApp" not in discovered_names, "Legacy non-KI directories must never be auto-discovered"


