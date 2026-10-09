from __future__ import annotations

import os
from pathlib import Path

from services.mcp.platform.environment import (
    EnvironmentKind,
    EnvironmentOperation,
    EnvironmentRequest,
    EnvironmentSpec,
    ResourceLimits,
)
from services.mcp.platform.process_workspace import (
    ProcessIsolatedWorkspaceTransport,
    ProcessSandboxPolicy,
)


def _spec() -> EnvironmentSpec:
    return EnvironmentSpec(
        environment_id="env_process",
        session_id="session_process",
        kind=EnvironmentKind.SELF_HOSTED,
        allowed_operations=frozenset({
            EnvironmentOperation.HEALTH,
            EnvironmentOperation.WORKSPACE_READ,
            EnvironmentOperation.WORKSPACE_WRITE,
        }),
        allowed_paths=("outputs",),
        resources=ResourceLimits(
            memory_bytes=128 * 1024 * 1024,
            max_processes=4,
            max_runtime_seconds=60,
        ),
        lease_seconds=30,
    )


def test_process_isolated_workspace_round_trip(tmp_path: Path) -> None:
    transport = ProcessIsolatedWorkspaceTransport(
        tmp_path,
        policy=ProcessSandboxPolicy(
            memory_bytes=256 * 1024 * 1024,
            max_processes=4,
            max_runtime_seconds=60,
            request_timeout_seconds=5,
        ),
    )
    spec = _spec()
    try:
        lease = transport.prepare(spec)
        health = transport.execute(
            lease,
            EnvironmentRequest(
                request_id="req_health",
                operation=EnvironmentOperation.HEALTH,
            ),
        )
        assert health["status"] == "healthy"

        written = transport.execute(
            lease,
            EnvironmentRequest(
                request_id="req_write",
                operation=EnvironmentOperation.WORKSPACE_WRITE,
                payload={"path": "outputs/result.txt", "content": "isolated"},
                idempotency_key="write_process_1",
            ),
        )
        assert written["size_bytes"] == 8
        read = transport.execute(
            lease,
            EnvironmentRequest(
                request_id="req_read",
                operation=EnvironmentOperation.WORKSPACE_READ,
                payload={"path": "outputs/result.txt"},
            ),
        )
        assert read["content"] == "isolated"
        renewed = transport.heartbeat(lease)
        assert renewed.revision == lease.revision + 1
        transport.shutdown(renewed, reason="test_complete")
        assert (tmp_path / "sessions" / "session_process" / "env_process" / "outputs" / "result.txt").read_text() == "isolated"
    finally:
        transport.close()


def test_windows_job_limits_are_attached_when_running_on_windows(tmp_path: Path) -> None:
    if os.name != "nt":
        return
    transport = ProcessIsolatedWorkspaceTransport(
        tmp_path,
        policy=ProcessSandboxPolicy(memory_bytes=128 * 1024 * 1024, max_processes=2),
    )
    try:
        transport.prepare(_spec())
        assert transport._windows_job_handle
    finally:
        transport.close()
