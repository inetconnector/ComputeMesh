"""Tests for bounded agent execution environments."""
from __future__ import annotations

import unittest

from services.mcp.platform.environment import (
    BoundedEnvironmentExecutor,
    EnvironmentExpired,
    EnvironmentKind,
    EnvironmentLease,
    EnvironmentOperation,
    EnvironmentPolicyDenied,
    EnvironmentRequest,
    EnvironmentSpec,
    EnvironmentState,
    ResourceLimits,
)


class _Transport:
    def __init__(self) -> None:
        self.prepared = 0
        self.heartbeats = 0
        self.executed = []
        self.shutdowns = []

    def prepare(self, spec):
        self.prepared += 1
        return EnvironmentLease("lease_1", spec.environment_id, 100.0, 110.0, 1)

    def heartbeat(self, lease):
        self.heartbeats += 1
        return EnvironmentLease(lease.lease_id, lease.environment_id, lease.issued_at, 120.0, lease.revision + 1)

    def execute(self, lease, request):
        self.executed.append(request)
        return {"ok": True, "request_id": request.request_id}

    def shutdown(self, lease, *, reason):
        self.shutdowns.append(reason)


class TestBoundedEnvironmentExecutor(unittest.TestCase):
    def test_mesh_lifecycle_uses_lease_heartbeat_and_clean_shutdown(self) -> None:
        now = [100.0]
        transport = _Transport()
        events = []
        spec = EnvironmentSpec(
            "env_1",
            "sess_1",
            kind=EnvironmentKind.MESH,
            node_id="node_1",
            model_id="qwen2.5:3b",
            allowed_operations=frozenset({EnvironmentOperation.INFERENCE, EnvironmentOperation.HEALTH}),
            resources=ResourceLimits(max_runtime_seconds=3600),
        )
        executor = BoundedEnvironmentExecutor(spec, transport=transport, event_sink=lambda name, payload: events.append((name, payload)), clock=lambda: now[0])

        self.assertEqual(executor.prepare(), EnvironmentState.READY)
        result = executor.execute(EnvironmentRequest("req_1", EnvironmentOperation.INFERENCE, {"prompt": "hello"}))
        self.assertTrue(result["ok"])
        self.assertEqual(executor.heartbeat().revision, 2)
        self.assertEqual(executor.shutdown(), EnvironmentState.CLOSED)
        self.assertEqual(transport.prepared, 1)
        self.assertEqual(len(transport.executed), 1)
        self.assertIn("environment.operation.completed", [name for name, _ in events])

    def test_writes_require_idempotency_and_paths_stay_in_workspace(self) -> None:
        transport = _Transport()
        spec = EnvironmentSpec(
            "env_2",
            "sess_2",
            kind=EnvironmentKind.SELF_HOSTED,
            allowed_operations=frozenset({EnvironmentOperation.WORKSPACE_WRITE}),
            allowed_paths=("outputs",),
            resources=ResourceLimits(max_runtime_seconds=3600),
        )
        executor = BoundedEnvironmentExecutor(spec, transport=transport, clock=lambda: 100.0)
        executor.prepare()
        with self.assertRaises(EnvironmentPolicyDenied):
            EnvironmentRequest("req_2", EnvironmentOperation.WORKSPACE_WRITE, {"path": "outputs/a.txt"})
        request = EnvironmentRequest("req_3", EnvironmentOperation.WORKSPACE_WRITE, {"path": "../secret"}, idempotency_key="idem_1")
        with self.assertRaises(ValueError):
            executor.execute(request)
        with self.assertRaises(EnvironmentPolicyDenied):
            executor.execute(EnvironmentRequest("req_4", EnvironmentOperation.WORKSPACE_WRITE, {"path": "private/a.txt"}, idempotency_key="idem_2"))

    def test_generic_shell_payload_is_rejected_and_lease_expiry_fails_closed(self) -> None:
        with self.assertRaises(EnvironmentPolicyDenied):
            EnvironmentRequest("req_5", EnvironmentOperation.INFERENCE, {"command": "whoami"})
        now = [100.0]
        transport = _Transport()
        spec = EnvironmentSpec("env_3", "sess_3", kind=EnvironmentKind.MESH, node_id="node_3", resources=ResourceLimits(max_runtime_seconds=3600))
        executor = BoundedEnvironmentExecutor(spec, transport=transport, clock=lambda: now[0])
        executor.prepare()
        now[0] = 111.0
        with self.assertRaises(EnvironmentExpired):
            executor.execute(EnvironmentRequest("req_6", EnvironmentOperation.INFERENCE, {}))
        self.assertEqual(executor.state, EnvironmentState.EXPIRED)


if __name__ == "__main__":
    unittest.main()
