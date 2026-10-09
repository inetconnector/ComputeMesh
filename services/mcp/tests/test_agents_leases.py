"""Tests for persistent node capacity reservations."""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from services.mcp.platform.leases import (
    LeaseState,
    NodeLeaseStore,
    ReservationConflict,
    ReservationDenied,
)
from services.mcp.platform.node_registry import NodeRegistry


class TestNodeLeaseStore(unittest.TestCase):
    def _ready_node(self, registry: NodeRegistry, node_id: str = "node_1") -> None:
        registry.discover(node_id, "http://node:8080")
        registry.mark_reachable(node_id)
        registry.record_capabilities(node_id, capabilities=("inference",), models=({"id": "qwen"},), profile_revision=1)
        registry.verify_identity(node_id, identity_key_id="key_1", evidence_digest="a" * 64)
        registry.mark_authenticated(node_id, principal_id="provider_1")
        registry.mark_prepared(node_id, preparation_digest="b" * 64)
        registry.record_benchmark(node_id, accepted=True, metrics={"ok": True})

    def test_capacity_idempotency_renew_release_and_restart(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            registry = NodeRegistry(Path(directory) / "nodes.sqlite3")
            self._ready_node(registry)
            database = Path(directory) / "leases.sqlite3"
            store = NodeLeaseStore(database, node_registry=registry)
            first = store.reserve(node_id="node_1", session_id="sess_1", turn_id="turn_1", model_id="qwen", capacity_limit=2, idempotency_key="idem_1")
            replay = store.reserve(node_id="node_1", session_id="sess_1", turn_id="turn_1", model_id="qwen", capacity_limit=2, idempotency_key="idem_1")
            self.assertEqual(first.lease_id, replay.lease_id)
            with self.assertRaises(ReservationConflict):
                store.reserve(node_id="node_1", session_id="sess_1", turn_id="turn_2", model_id="other", capacity_limit=2, idempotency_key="idem_1")
            second = store.reserve(node_id="node_1", session_id="sess_2", turn_id="turn_2", model_id="qwen", capacity_limit=2, idempotency_key="idem_2")
            self.assertEqual(len(store.active_for_node("node_1")), 2)
            with self.assertRaises(ReservationDenied):
                store.reserve(node_id="node_1", session_id="sess_3", turn_id="turn_3", model_id="qwen", capacity_limit=2, idempotency_key="idem_3")
            renewed = store.renew(first.lease_id, ttl_seconds=600)
            self.assertGreater(renewed.expires_at, first.expires_at)
            self.assertEqual(store.release(second.lease_id).status, LeaseState.RELEASED)
            store.close()
            reopened = NodeLeaseStore(database, node_registry=registry)
            try:
                self.assertEqual(reopened.get(first.lease_id).status, LeaseState.ACTIVE)
            finally:
                reopened.close()
                registry.close()

    def test_unready_nodes_cannot_be_reserved(self) -> None:
        registry = NodeRegistry()
        try:
            registry.discover("node_2", "http://node:8081")
            store = NodeLeaseStore(node_registry=registry)
            try:
                with self.assertRaises(ReservationDenied):
                    store.reserve(node_id="node_2", session_id="sess_1", turn_id="turn_1", model_id="qwen", idempotency_key="idem_1")
            finally:
                store.close()
        finally:
            registry.close()


if __name__ == "__main__":
    unittest.main()
