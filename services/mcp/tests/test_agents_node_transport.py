"""Tests for authenticated NodeSession to Agent node-registry admission."""
from __future__ import annotations

import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from services.mcp.platform.node_registry import NodeLifecycle, NodeRegistry, NodeStateConflict
from services.mcp.platform.node_transport import (
    AuthenticatedNodeRegistrySync,
    AuthenticatedNodeSyncError,
)


class FakeSession:
    def __init__(self, *, state: str = "ready", revision: int = 4, expires: datetime | None = None) -> None:
        self.session_id = "session_1"
        self.state = state
        self.revision = 7
        self.node_id = "node_1"
        self.principal_id = "provider_1"
        self.key_id = "key_1"
        self.credential_expires_at = expires or (datetime.now(timezone.utc) + timedelta(minutes=10))
        self.negotiated_capabilities = frozenset({"execution_attestation_v1", "inference"})
        self.profile_revision = revision


class FakeControlClient:
    def __init__(self, connected: bool) -> None:
        self.connected = connected

    def is_connected(self, node_id: str) -> bool:
        return self.connected


class TestAuthenticatedNodeRegistrySync(unittest.TestCase):
    def _profile(self, revision: int = 4) -> dict[str, object]:
        return {"node_id": "node_1", "profile_revision": revision, "private_score": "must not be copied"}

    def _models(self) -> list[dict[str, object]]:
        return [{"id": "qwen", "context_tokens": 32768, "free_vram_bytes": 16_000_000_000, "secret": "drop"}]

    def test_authenticated_session_becomes_routable_and_refreshes(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            registry = NodeRegistry(Path(directory) / "nodes.sqlite3")
            try:
                sync = AuthenticatedNodeRegistrySync(registry)
                first = sync.sync(
                    node_id="node_1",
                    endpoint="tls://node-1",
                    session=FakeSession(),
                    profile=self._profile(),
                    models=self._models(),
                    benchmark={"decode_tokens_per_second": 30},
                )
                self.assertEqual(first.node.status, NodeLifecycle.READY)
                self.assertEqual(first.node.principal_id, "provider_1")
                self.assertEqual(first.node.models[0]["id"], "qwen")
                self.assertNotIn("secret", first.node.models[0])
                refreshed = sync.sync(
                    node_id="node_1",
                    endpoint="tls://node-1",
                    session=FakeSession(revision=5),
                    profile=self._profile(5),
                    models=[{"id": "qwen", "context_tokens": 65536}],
                )
                self.assertEqual(refreshed.node.status, NodeLifecycle.READY)
                self.assertEqual(refreshed.node.profile_revision, 5)
            finally:
                registry.close()

    def test_expired_or_mismatched_sessions_fail_closed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            registry = NodeRegistry(Path(directory) / "nodes.sqlite3")
            try:
                sync = AuthenticatedNodeRegistrySync(registry)
                with self.assertRaises(AuthenticatedNodeSyncError):
                    sync.sync(
                        node_id="node_1",
                        endpoint="tls://node-1",
                        session=FakeSession(expires=datetime.now(timezone.utc) - timedelta(seconds=1)),
                        profile=self._profile(),
                        models=self._models(),
                    )
                with self.assertRaises(AuthenticatedNodeSyncError):
                    sync.sync(
                        node_id="node_1",
                        endpoint="tls://node-1",
                        session=FakeSession(),
                        profile=self._profile(3),
                        models=self._models(),
                    )
            finally:
                registry.close()

    def test_profile_revision_cannot_move_backwards(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            registry = NodeRegistry(Path(directory) / "nodes.sqlite3")
            try:
                sync = AuthenticatedNodeRegistrySync(registry)
                sync.sync(node_id="node_1", endpoint="tls://node-1", session=FakeSession(revision=4), profile=self._profile(), models=self._models())
                with self.assertRaises((AuthenticatedNodeSyncError, NodeStateConflict)):
                    sync.sync(node_id="node_1", endpoint="tls://node-1", session=FakeSession(revision=3), profile=self._profile(3), models=self._models())
            finally:
                registry.close()

    def test_live_control_channel_is_required_when_bound(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            registry = NodeRegistry(Path(directory) / "nodes.sqlite3")
            try:
                sync = AuthenticatedNodeRegistrySync(registry, control_client=FakeControlClient(False))
                with self.assertRaises(AuthenticatedNodeSyncError):
                    sync.sync(node_id="node_1", endpoint="tls://node-1", session=FakeSession(), profile=self._profile(), models=self._models())
            finally:
                registry.close()


if __name__ == "__main__":
    unittest.main()
