"""Tests for safe automatic LAN node onboarding."""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from services.mcp.platform.node_onboarding import (
    NodeAuthenticationRequired,
    NodeOnboardingCoordinator,
)
from services.mcp.platform.node_registry import NodeLifecycle, NodeRegistry


class TestNodeOnboardingCoordinator(unittest.TestCase):
    def test_authentication_challenge_stays_visible_and_requires_pairing(self) -> None:
        registry = NodeRegistry()
        try:
            result = NodeOnboardingCoordinator(registry).onboard(
                node_id="lan_node",
                endpoint="http://192.0.2.10:8080",
                probe=lambda node: {"authentication_required": True, "capabilities": [], "models": [], "profile_revision": 1},
            )
            self.assertEqual(result.status, "manual_pairing_required")
            self.assertTrue(result.manual_pairing_required)
            self.assertEqual(result.node.status, NodeLifecycle.QUARANTINED)
            self.assertEqual(registry.routable_nodes(), ())
        finally:
            registry.close()

    def test_authenticated_probe_prepares_and_benchmarks_node(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            registry = NodeRegistry(Path(directory) / "nodes.sqlite3")
            try:
                prepared = []
                result = NodeOnboardingCoordinator(registry).onboard(
                    node_id="lan_node",
                    endpoint="tls://lan_node",
                    probe=lambda node: {
                        "capabilities": ["inference_v1"],
                        "models": [{"id": "qwen", "free_vram_bytes": 16_000}],
                        "profile_revision": 3,
                        "identity_key_id": "key_lan_node",
                        "identity_evidence_digest": "a" * 64,
                        "principal_id": "provider_lan_node",
                    },
                    prepare=lambda node: prepared.append(node.node_id) or "b" * 64,
                    benchmark=lambda node: (True, {"decode_tokens_per_second": 42}),
                )
                self.assertEqual(result.status, "ready")
                self.assertEqual(result.node.status, NodeLifecycle.READY)
                self.assertEqual(prepared, ["lan_node"])
                self.assertEqual(registry.routable_nodes()[0].models[0]["id"], "qwen")
            finally:
                registry.close()

    def test_probe_exception_is_quarantined_and_never_trusted(self) -> None:
        registry = NodeRegistry()
        try:
            result = NodeOnboardingCoordinator(registry).onboard(
                node_id="lan_node",
                endpoint="http://192.0.2.11:8080",
                probe=lambda node: (_ for _ in ()).throw(NodeAuthenticationRequired("pairing")),
            )
            self.assertEqual(result.status, "manual_pairing_required")
            self.assertEqual(result.node.status, NodeLifecycle.QUARANTINED)
        finally:
            registry.close()


if __name__ == "__main__":
    unittest.main()
