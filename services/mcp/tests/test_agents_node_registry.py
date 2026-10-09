"""Tests for safe automatic node discovery and onboarding state."""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from services.mcp.platform.node_registry import NodeLifecycle, NodeRegistry, NodeStateConflict


class TestNodeRegistry(unittest.TestCase):
    def test_discovery_is_visible_but_not_routable_until_full_onboarding(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            registry = NodeRegistry(Path(directory) / "nodes.sqlite3")
            try:
                node = registry.discover("node_1", "http://192.168.1.20:8080", discovery_source="lan")
                self.assertEqual(node.status, NodeLifecycle.DISCOVERED)
                self.assertEqual(registry.routable_nodes(), ())
                registry.mark_reachable(node.node_id)
                registry.record_capabilities(
                    node.node_id,
                    capabilities=("inference", "tool_call"),
                    models=({"id": "qwen2.5:3b", "vram_bytes": 4_000_000_000},),
                    profile_revision=7,
                )
                with self.assertRaises(NodeStateConflict):
                    registry.mark_authenticated(node.node_id, principal_id="node_1")
                registry.verify_identity(node.node_id, identity_key_id="key_1", evidence_digest="a" * 64)
                registry.mark_authenticated(node.node_id, principal_id="provider_1")
                registry.mark_prepared(node.node_id, preparation_digest="b" * 64)
                registry.record_benchmark(node.node_id, accepted=True, metrics={"tokens_per_second": 12.3})
                routable = registry.routable_nodes()
                self.assertEqual([item.node_id for item in routable], ["node_1"])
                self.assertEqual(routable[0].models[0]["id"], "qwen2.5:3b")
            finally:
                registry.close()

    def test_auth_challenge_keeps_node_visible_and_quarantined(self) -> None:
        registry = NodeRegistry()
        try:
            node = registry.discover("node_2", "http://192.168.1.21:8080")
            registry.mark_reachable(node.node_id)
            quarantined = registry.mark_authentication_required(node.node_id)
            self.assertEqual(quarantined.status, NodeLifecycle.QUARANTINED)
            self.assertTrue(quarantined.auth_required)
            self.assertEqual(len(registry.list_visible()), 1)
            self.assertEqual(registry.routable_nodes(), ())
        finally:
            registry.close()

    def test_revoke_is_terminal_and_survives_restart(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            database = Path(directory) / "nodes.sqlite3"
            first = NodeRegistry(database)
            node = first.discover("node_3", "udp://192.168.1.22:4269")
            first.revoke(node.node_id, reason="operator_revoked")
            first.close()
            reopened = NodeRegistry(database)
            try:
                self.assertEqual(reopened.get("node_3").status, NodeLifecycle.REVOKED)
                with self.assertRaises(NodeStateConflict):
                    reopened.mark_reachable("node_3")
            finally:
                reopened.close()

    def test_stale_routable_node_is_quarantined_until_authenticated_refresh(self) -> None:
        registry = NodeRegistry()
        try:
            node = registry.discover("node_stale", "tls://node-stale")
            registry.mark_reachable(node.node_id)
            registry.record_capabilities(
                node.node_id,
                capabilities=("inference",),
                models=({"id": "qwen"},),
                profile_revision=1,
            )
            registry.verify_identity(node.node_id, identity_key_id="key_stale", evidence_digest="a" * 64)
            registry.mark_authenticated(node.node_id, principal_id="provider_stale")
            registry.mark_prepared(node.node_id, preparation_digest="b" * 64)
            registry.record_benchmark(node.node_id, accepted=True, metrics={"tokens_per_second": 1})

            current = registry.get(node.node_id)
            stale = registry.reconcile_stale_nodes(10, now=current.last_seen + 11)
            self.assertEqual([item.node_id for item in stale], [node.node_id])
            self.assertEqual(registry.get(node.node_id).status, NodeLifecycle.QUARANTINED)
            self.assertEqual(registry.routable_nodes(), ())
            self.assertEqual(registry.list_events(node.node_id)[-1].event_type, "node.status_changed")
            self.assertIn("heartbeat_stale", registry.get(node.node_id).reason)
        finally:
            registry.close()

    def test_stale_reconciler_rejects_non_positive_window(self) -> None:
        registry = NodeRegistry()
        try:
            with self.assertRaises(ValueError):
                registry.reconcile_stale_nodes(0)
        finally:
            registry.close()


if __name__ == "__main__":
    unittest.main()
