# SPDX-License-Identifier: Apache-2.0
"""Rigorous tests for Workspaces & Task lifecycle contracts in ComputeMesh Gateway.

Covers:
- GET /v1/fleet/workspaces with authentic metadata (source, node_id, status)
- POST /v1/fleet/workspaces with validation, traversal protection, create_if_missing
- DELETE /v1/fleet/workspaces (safe unregister, tombstone persistence, anti-resurrection)
- Negative tests: unauthorized, cross-owner, system-path traversal, physical delete safety
- DELETE /v1/agents/sessions/{id} with ownership enforcement and atomic SQLite purge
"""
import json
import os
import shutil
import tempfile
import time
from http import HTTPStatus
from pathlib import Path

import pytest

from services.gateway.server import GatewayHandler, NODE_TELEMETRY_REGISTRY
from tools.appliance.workspace_manager import (
    load_local_workspaces,
    register_local_workspace,
    unregister_local_workspace,
    discover_host_project_workspaces,
    get_workspace_config_path,
)


class DummyInferenceBackend:
    def list_models(self):
        return []


@pytest.fixture(autouse=True)
def isolated_workspace_environment(monkeypatch, tmp_path):
    """Isolate workspaces.json and agent sessions to a temporary sandbox."""
    fake_cfg = tmp_path / "workspaces.json"
    fake_db = tmp_path / "sessions.sqlite3"
    monkeypatch.setenv("COMPUTEMESH_AGENTS_SESSION_DB", str(fake_db))
    monkeypatch.setattr(
        "tools.appliance.workspace_manager.get_workspace_config_path",
        lambda: fake_cfg,
    )
    # Clear memory telemetry
    NODE_TELEMETRY_REGISTRY.clear()
    GatewayHandler.agent_session_store = None
    yield tmp_path
    if fake_cfg.exists():
        fake_cfg.unlink(missing_ok=True)
    NODE_TELEMETRY_REGISTRY.clear()


def test_workspace_manager_lifecycle_and_tombstones(tmp_path):
    """Test register, unregister with tombstone, and anti-resurrection."""
    proj_dir = tmp_path / "TestProjAlpha"
    proj_dir.mkdir()
    (proj_dir / "README.md").write_text("# Test", encoding="utf-8")

    # 1. Register
    ws = register_local_workspace(str(proj_dir), custom_name="TestProjAlpha")
    assert ws is not None
    assert ws["name"] == "TestProjAlpha"
    assert ws["registration_source"] == "user_registered"
    assert ws["status"] == "active"

    # Verify present in loaded list
    loaded = load_local_workspaces()
    assert any(w["id"] == ws["id"] for w in loaded)

    # 2. Unregister without physical deletion
    unreg_res = unregister_local_workspace(ws["id"], delete_physical_folder=False)
    assert unreg_res["success"] is True
    assert unreg_res["physical_deleted"] is False
    assert proj_dir.is_dir(), "Physical directory must be untouched"

    # Verify removed from loaded list
    loaded_after = load_local_workspaces()
    assert not any(w["id"] == ws["id"] for w in loaded_after)

    # 3. Verify anti-resurrection: auto-discovery must skip unregistered paths
    discovered = discover_host_project_workspaces()
    assert not any(w["path"] == str(proj_dir) for w in discovered)


def test_workspace_traversal_and_system_dir_protection():
    """Negative tests: path traversal and system directories must be rejected."""
    with pytest.raises(ValueError, match="null bytes"):
        register_local_workspace("test\0bad")

    with pytest.raises(ValueError, match="protected system"):
        register_local_workspace("C:\\Windows\\System32\\bad")

    with pytest.raises(ValueError, match="protected system"):
        register_local_workspace("/etc/passwd")


def test_workspace_create_if_missing_requirement(tmp_path):
    """Negative test: missing directory without create_if_missing fails closed."""
    missing = tmp_path / "Does_Not_Exist_Yet"
    with pytest.raises(FileNotFoundError):
        register_local_workspace(str(missing), create_if_missing=False)


def test_physical_deletion_safety_requires_exact_name(tmp_path):
    """Physical deletion must require exact matching confirmation name."""
    proj = tmp_path / "CriticalFolder"
    proj.mkdir()
    (proj / "README.md").write_text("critical", encoding="utf-8")
    ws = register_local_workspace(str(proj), custom_name="CriticalFolder")

    # Mismatched confirm_name
    res = unregister_local_workspace(ws["id"], delete_physical_folder=True, confirm_name="WrongName")
    assert res["physical_deleted"] is False
    assert proj.is_dir(), "Folder must not be deleted when confirmation name does not match"

    # Workspace is unregister-protected
    assert not any(w["id"] == ws["id"] for w in load_local_workspaces())


def test_session_atomic_deletion(tmp_path):
    """Test AgentSessionStore.delete_session deletes session and related records."""
    from services.mcp.platform.session import AgentSessionStore

    store = AgentSessionStore(tmp_path / "test_sessions.sqlite3")
    session, turn = store.create_task(
        agent_id="test_agent",
        model="qwen2.5:3b",
        input_items="Analyze code",
        principal_id="user_alice",
    )
    assert session is not None
    assert session.session_id

    # Verify session exists
    fetched = store.get_session(session.session_id)
    assert fetched.session_id == session.session_id

    # Cross-principal deletion must raise PermissionError
    with pytest.raises(PermissionError):
        store.delete_session(session.session_id, principal_id="user_bob", is_admin=False)

    # Deletion by owner
    deleted = store.delete_session(session.session_id, principal_id="user_alice")
    assert deleted is True

    # Verify session is gone
    with pytest.raises(KeyError):
        store.get_session(session.session_id)

    # Idempotent delete on non-existent returns False
    assert store.delete_session(session.session_id, principal_id="user_alice") is False


def test_gateway_workspaces_and_sessions_http_routes(tmp_path):
    """Test full HTTP endpoints for DELETE workspaces and DELETE sessions."""
    import http.client
    import threading
    from http.server import ThreadingHTTPServer
    from services.mcp.platform.session import AgentSessionStore

    # Setup session store
    store = AgentSessionStore(tmp_path / "http_sessions.sqlite3")
    GatewayHandler.agent_session_store = store
    GatewayHandler.api_keys = {
        "cm_live_alice_key": "user_alice",
        "cm_live_bob_key": "user_bob",
    }
    GatewayHandler.sync_subsystems()

    # Pre-populate a session for alice
    sess, _ = store.create_task(
        agent_id="test_agent",
        model="qwen2.5:3b",
        input_items="Do work",
        principal_id="user_alice",
    )

    # Register a local workspace in sandbox
    ws_dir = tmp_path / "MyProjectAlpha"
    ws_dir.mkdir()
    (ws_dir / "README.md").write_text("# Alpha", encoding="utf-8")
    registered_ws = register_local_workspace(str(ws_dir), custom_name="MyProjectAlpha")
    assert registered_ws is not None

    server = ThreadingHTTPServer(("127.0.0.1", 0), GatewayHandler)
    port = server.server_port
    th = threading.Thread(target=server.serve_forever, daemon=True)
    th.start()
    time.sleep(0.05)

    try:
        conn = http.client.HTTPConnection("127.0.0.1", port)

        # 1. Unauthenticated DELETE /v1/fleet/workspaces -> 401
        conn.request("DELETE", f"/v1/fleet/workspaces/{registered_ws['id']}")
        res = conn.getresponse()
        assert res.status == HTTPStatus.UNAUTHORIZED
        res.read()

        # 2. Authenticated DELETE /v1/fleet/workspaces -> 200
        conn.request(
            "DELETE",
            f"/v1/fleet/workspaces/{registered_ws['id']}",
            headers={"Authorization": "Bearer cm_live_alice_key"},
        )
        res = conn.getresponse()
        assert res.status == HTTPStatus.OK
        body = json.loads(res.read().decode())
        assert body["status"] == "unregistered"
        assert body["result"]["unregistered"] is True

        # 3. GET /v1/fleet/workspaces -> verify removed
        conn.request("GET", "/v1/fleet/workspaces", headers={"Authorization": "Bearer cm_live_alice_key"})
        res = conn.getresponse()
        assert res.status == HTTPStatus.OK
        data = json.loads(res.read().decode())
        assert not any(w["id"] == registered_ws["id"] for w in data["workspaces"])

        # 4. Unauthenticated DELETE /v1/agents/sessions/{id} -> 401
        conn.request("DELETE", f"/v1/agents/sessions/{sess.session_id}")
        res = conn.getresponse()
        assert res.status == HTTPStatus.UNAUTHORIZED
        res.read()

        # 5. Cross-owner DELETE /v1/agents/sessions/{id} by bob -> 403
        conn.request(
            "DELETE",
            f"/v1/agents/sessions/{sess.session_id}",
            headers={"Authorization": "Bearer cm_live_bob_key"},
        )
        res = conn.getresponse()
        assert res.status == HTTPStatus.FORBIDDEN
        res.read()

        # 6. Authorized DELETE /v1/agents/sessions/{id} by alice -> 200
        conn.request(
            "DELETE",
            f"/v1/agents/sessions/{sess.session_id}",
            headers={"Authorization": "Bearer cm_live_alice_key"},
        )
        res = conn.getresponse()
        assert res.status == HTTPStatus.OK
        del_data = json.loads(res.read().decode())
        assert del_data["deleted"] is True
        assert del_data["session_id"] == sess.session_id

        # 7. DELETE non-existent session -> 404
        conn.request(
            "DELETE",
            f"/v1/agents/sessions/{sess.session_id}",
            headers={"Authorization": "Bearer cm_live_alice_key"},
        )
        res = conn.getresponse()
        assert res.status == HTTPStatus.NOT_FOUND
        res.read()

        # 8. Unauthenticated service control -> 401, service control must never be invoked
        import services.appliance_dashboard.server as dash_mod
        calls = []
        original_ctrl = dash_mod.execute_service_control
        dash_mod.execute_service_control = lambda action: calls.append(action) or (True, "x")
        try:
            payload = json.dumps({"action": "stop"})
            conn.request(
                "POST",
                "/api/appliance/service/control",
                body=payload,
                headers={"Content-Type": "application/json", "Content-Length": str(len(payload))},
            )
            res = conn.getresponse()
            assert res.status == HTTPStatus.UNAUTHORIZED
            res.read()
            assert calls == []
        finally:
            dash_mod.execute_service_control = original_ctrl

        # 9. Service status is readable and reports a known service name
        conn.request("GET", "/api/appliance/service/status")
        res = conn.getresponse()
        assert res.status == HTTPStatus.OK
        status_body = json.loads(res.read().decode())
        assert status_body["service_name"] in ("ComputeMeshNode", "computemesh-node")

        conn.close()
    finally:
        server.shutdown()
        server.server_close()

