# SPDX-License-Identifier: Apache-2.0
"""Tests for the shell-free local self-hosted workspace transport."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from services.mcp.platform.environment import (
    BoundedEnvironmentExecutor,
    EnvironmentKind,
    EnvironmentOperation,
    EnvironmentPolicyDenied,
    EnvironmentRequest,
    EnvironmentSpec,
    ResourceLimits,
)
from services.mcp.platform.workspace import LocalWorkspaceTransport


class TestLocalWorkspaceTransport(unittest.TestCase):
    def test_workspace_read_write_is_atomic_and_bounded(self):
        with tempfile.TemporaryDirectory() as directory:
            transport = LocalWorkspaceTransport(Path(directory))
            spec = EnvironmentSpec(
                "env_local",
                "session_local",
                kind=EnvironmentKind.SELF_HOSTED,
                allowed_operations=frozenset({EnvironmentOperation.WORKSPACE_READ, EnvironmentOperation.WORKSPACE_WRITE, EnvironmentOperation.HEALTH}),
                allowed_paths=("outputs",),
                resources=ResourceLimits(max_runtime_seconds=3600),
            )
            executor = BoundedEnvironmentExecutor(spec, transport=transport)
            executor.prepare()
            write = executor.execute(EnvironmentRequest("req_write", EnvironmentOperation.WORKSPACE_WRITE, {"path": "outputs/a.txt", "content": "hello"}, idempotency_key="write_1"))
            replay = executor.execute(EnvironmentRequest("req_write2", EnvironmentOperation.WORKSPACE_WRITE, {"path": "outputs/a.txt", "content": "hello"}, idempotency_key="write_1"))
            read = executor.execute(EnvironmentRequest("req_read", EnvironmentOperation.WORKSPACE_READ, {"path": "outputs/a.txt"}))
            self.assertEqual(write["size_bytes"], 5)
            self.assertTrue(replay["idempotency_replay"])
            self.assertEqual(read["content"], "hello")

    def test_reads_and_writes_cannot_escape_allowlist_or_use_shell(self):
        with tempfile.TemporaryDirectory() as directory:
            transport = LocalWorkspaceTransport(Path(directory))
            spec = EnvironmentSpec(
                "env_safe",
                "session_safe",
                kind=EnvironmentKind.SELF_HOSTED,
                allowed_operations=frozenset({EnvironmentOperation.WORKSPACE_READ, EnvironmentOperation.WORKSPACE_WRITE}),
                allowed_paths=("outputs",),
                resources=ResourceLimits(max_runtime_seconds=3600),
            )
            executor = BoundedEnvironmentExecutor(spec, transport=transport)
            executor.prepare()
            with self.assertRaises(EnvironmentPolicyDenied):
                executor.execute(EnvironmentRequest("req_escape", EnvironmentOperation.WORKSPACE_READ, {"path": "private/a.txt"}))
            with self.assertRaises(EnvironmentPolicyDenied):
                executor.execute(EnvironmentRequest("req_shell", EnvironmentOperation.WORKSPACE_WRITE, {"path": "outputs/a", "content": "x", "command": "whoami"}, idempotency_key="write_2"))

    def test_transport_rejects_mesh_without_nodeos_adapter(self):
        with tempfile.TemporaryDirectory() as directory:
            transport = LocalWorkspaceTransport(Path(directory))
            spec = EnvironmentSpec(
                "env_mesh",
                "session_mesh",
                kind=EnvironmentKind.MESH,
                node_id="node_1",
                resources=ResourceLimits(max_runtime_seconds=3600),
            )
            with self.assertRaises(Exception):
                transport.prepare(spec)


if __name__ == "__main__":
    unittest.main()
