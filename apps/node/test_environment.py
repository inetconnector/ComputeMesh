from __future__ import annotations

import base64
import hashlib
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from apps.node.environment import NodeEnvironmentError, NodeEnvironmentExecutor
from protocol.node_session import NodeSessionState, SessionSnapshot
from services.mcp.platform.environment import EnvironmentPolicyDenied


def _session(node_id: str = "node-a") -> SessionSnapshot:
    return SessionSnapshot(
        session_id="session-a",
        state=NodeSessionState.READY,
        revision=7,
        protocol_major=1,
        protocol_minor=0,
        node_id=node_id,
        principal_id="provider-a",
        auth_method="ed25519_challenge_v1",
        credential_expires_at=datetime.now(UTC) + timedelta(minutes=5),
        negotiated_capabilities=frozenset({"mesh_environment_v1"}),
        profile_revision=3,
        drain_reason=None,
        close_reason=None,
    )


def _prepare_payload(*, node_id: str = "node-a", environment_id: str = "env_1") -> dict[str, object]:
    return {
        "schema_version": 1,
        "session_id": "session-a",
        "session_revision": 7,
        "node_id": node_id,
        "environment_id": environment_id,
        "operation": "prepare",
        "spec": {
            "kind": "mesh",
            "model_id": "qwen2.5:3b",
            "allowed_operations": ["health", "inference", "workspace_read", "workspace_write"],
            "allowed_paths": ["outputs"],
            "network_allowlist": [],
            "resources": {
                "cpu_millis": 1000,
                "memory_bytes": 536870912,
                "vram_bytes": 0,
                "max_processes": 4,
                "max_runtime_seconds": 3600,
            },
            "lease_seconds": 300,
        },
    }


def _execute_payload(
    lease: dict[str, object],
    operation_name: str,
    payload: dict[str, object],
    *,
    request_id: str,
    idempotency_key: str | None = None,
) -> dict[str, object]:
    result = {
        "schema_version": 1,
        "session_id": "session-a",
        "session_revision": 7,
        "node_id": "node-a",
        "environment_id": "env_1",
        "operation": "execute",
        "lease_id": lease["lease_id"],
        "lease_revision": lease["lease_revision"],
        "request_id": request_id,
        "operation_name": operation_name,
        "payload": payload,
    }
    if idempotency_key is not None:
        result["idempotency_key"] = idempotency_key
    return result


def test_node_environment_executor_runs_bounded_workspace_lifecycle(tmp_path: Path) -> None:
    executor = NodeEnvironmentExecutor(node_id="node-a", root=str(tmp_path))
    session = _session()
    lease = executor(session, _prepare_payload())
    assert lease["lease_revision"] == 1

    write = executor(session, _execute_payload(lease, "workspace_write", {
        "path": "outputs/result.txt", "content": "done", "overwrite": False,
    }, request_id="write_1", idempotency_key="write_key_1"))
    assert write["result"]["size_bytes"] == 4  # type: ignore[index]
    read = executor(session, _execute_payload(lease, "workspace_read", {"path": "outputs/result.txt"}, request_id="read_1"))
    assert read["result"]["content"] == "done"  # type: ignore[index]

    heartbeat = dict(_prepare_payload())
    heartbeat.update({"operation": "heartbeat", "lease_id": lease["lease_id"], "lease_revision": lease["lease_revision"]})
    renewed = executor(session, heartbeat)
    assert renewed["lease_revision"] == 2

    shutdown = dict(_prepare_payload())
    shutdown.update({"operation": "shutdown", "lease_id": renewed["lease_id"], "lease_revision": renewed["lease_revision"], "reason": "done"})
    assert executor(session, shutdown) == {"status": "ok"}


def test_node_environment_executor_binds_model_and_rejects_policy_escape(tmp_path: Path) -> None:
    calls: list[dict[str, object]] = []

    def inference(_session: SessionSnapshot, request: dict[str, object], cancel_event: object | None = None) -> dict[str, object]:
        calls.append(request)
        assert cancel_event is None
        return {"output": "hello", "model_id": request["model_id"]}

    executor = NodeEnvironmentExecutor(node_id="node-a", root=str(tmp_path), inference_executor=inference)
    session = _session()
    lease = executor(session, _prepare_payload())
    result = executor(session, _execute_payload(lease, "inference", {
        "messages": [{"role": "user", "content": "hi"}], "max_tokens": 8,
    }, request_id="infer_1"))
    assert result["result"]["output"] == "hello"  # type: ignore[index]
    assert calls[0]["model_id"] == "qwen2.5:3b"

    with pytest.raises(NodeEnvironmentError, match="model"):
        executor(session, _execute_payload(lease, "inference", {
            "model_id": "another-model", "messages": [], "max_tokens": 8,
        }, request_id="wrong_model"))

    with pytest.raises(EnvironmentPolicyDenied):
        executor(session, _execute_payload(lease, "workspace_read", {"path": "../secret"}, request_id="escape_1"))

    wrong_session = _session("node-b")
    with pytest.raises(NodeEnvironmentError, match="node"):
        executor(wrong_session, _execute_payload(lease, "health", {}, request_id="wrong_node"))


def test_node_environment_executor_stages_verified_resumable_artifact(tmp_path: Path) -> None:
    raw = b"artifact payload across two chunks"
    artifact_id = "sha256:" + hashlib.sha256(raw).hexdigest()
    payload = _prepare_payload()
    payload["spec"]["allowed_operations"] = ["artifact_stage", "artifact_stage_status"]  # type: ignore[index]
    executor = NodeEnvironmentExecutor(node_id="node-a", root=str(tmp_path))
    session = _session()
    lease = executor(session, payload)

    status = executor(session, _execute_payload(lease, "artifact_stage_status", {
        "path": "outputs/model.bin", "artifact_id": artifact_id, "total_bytes": len(raw),
    }, request_id="stage_status_1"))
    assert status["result"]["next_offset"] == 0  # type: ignore[index]

    first = executor(session, _execute_payload(lease, "artifact_stage", {
        "path": "outputs/model.bin", "artifact_id": artifact_id, "total_bytes": len(raw),
        "offset": 0, "content_base64": base64.b64encode(raw[:10]).decode("ascii"), "final": False,
    }, request_id="stage_1", idempotency_key="stage_key_1"))
    replay = executor(session, _execute_payload(lease, "artifact_stage", {
        "path": "outputs/model.bin", "artifact_id": artifact_id, "total_bytes": len(raw),
        "offset": 0, "content_base64": base64.b64encode(raw[:10]).decode("ascii"), "final": False,
    }, request_id="stage_1_replay", idempotency_key="stage_key_1"))
    assert first["result"]["next_offset"] == 10  # type: ignore[index]
    assert replay["result"]["idempotency_replay"] is True  # type: ignore[index]

    final = executor(session, _execute_payload(lease, "artifact_stage", {
        "path": "outputs/model.bin", "artifact_id": artifact_id, "total_bytes": len(raw),
        "offset": 10, "content_base64": base64.b64encode(raw[10:]).decode("ascii"), "final": True,
    }, request_id="stage_2", idempotency_key="stage_key_2"))
    assert final["result"]["complete"] is True  # type: ignore[index]
    target = tmp_path / "sessions" / "session-a" / "env_1" / "outputs" / "model.bin"
    assert target.read_bytes() == raw
