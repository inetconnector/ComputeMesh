"""Capability-aware node routing tests."""
from __future__ import annotations

import unittest

from services.mcp.platform.node_registry import NodeLifecycle, NodeRecord
from services.mcp.platform.node_routing import CapabilityAwareNodeRouter, NodeRouteRequirement


def _node(node_id: str, *, status=NodeLifecycle.READY, models=(), capabilities=("inference",), auth=True):
    return NodeRecord(
        node_id=node_id,
        endpoint=f"http://{node_id}:8080",
        discovery_source="lan",
        status=status,
        principal_id="provider" if auth else "",
        identity_key_id="key" if auth else "",
        capabilities=tuple(capabilities),
        models=tuple(models),
        profile_revision=1,
        benchmark={"accepted": True},
        auth_required=not auth,
        reason="",
        version=1,
        first_seen=1.0,
        last_seen=1.0,
        updated_at=1.0,
    )


class TestCapabilityAwareNodeRouter(unittest.TestCase):
    def test_selects_only_verified_ready_model_capable_node(self) -> None:
        nodes = (
            _node("node_bad", models=({"id": "other", "free_vram_bytes": 20},)),
            _node("node_good", models=({"id": "qwen", "free_vram_bytes": 16_000, "context_tokens": 32_768, "capabilities": ["tool_call"]},), capabilities=("inference", "tool_call")),
            _node("node_unknown", status=NodeLifecycle.DISCOVERED, models=({"id": "qwen", "free_vram_bytes": 99_000},)),
        )
        decision = CapabilityAwareNodeRouter().route(nodes, NodeRouteRequirement(model_id="qwen", required_capabilities=frozenset({"tool_call"}), min_free_vram_bytes=8_000, min_context_tokens=16_000))
        self.assertEqual(decision.status, "ROUTED")
        self.assertEqual(decision.selected.node_id, "node_good")
        self.assertTrue(any("model_not_advertised" in candidate.reasons for candidate in decision.candidates if candidate.node_id == "node_bad"))

    def test_no_capable_node_is_explicit_and_does_not_fallback_to_unverified(self) -> None:
        decision = CapabilityAwareNodeRouter().route(
            (_node("node_unverified", status=NodeLifecycle.DISCOVERED, models=({"id": "qwen", "free_vram_bytes": 99_000},), auth=False),),
            NodeRouteRequirement(model_id="qwen"),
        )
        self.assertEqual(decision.status, "NO_CAPABLE_NODE")
        self.assertIsNone(decision.selected)
        self.assertIn("node_not_ready", decision.candidates[0].reasons)

    def test_routes_by_verified_throughput_and_latency_constraints(self) -> None:
        nodes = (
            _node(
                "node_fast",
                models=({
                    "id": "qwen",
                    "free_vram_bytes": 16_000,
                    "context_tokens": 32_768,
                    "decode_tokens_per_second": 80,
                    "latency_ms": 45,
                },),
            ),
            _node(
                "node_slow",
                models=({
                    "id": "qwen",
                    "free_vram_bytes": 32_000,
                    "context_tokens": 32_768,
                    "decode_tokens_per_second": 20,
                    "latency_ms": 10,
                },),
            ),
        )
        router = CapabilityAwareNodeRouter()
        decision = router.route(
            nodes,
            NodeRouteRequirement(
                model_id="qwen",
                min_decode_tokens_per_second=50,
                max_latency_ms=100,
            ),
        )
        self.assertEqual(decision.selected.node_id, "node_fast")
        self.assertEqual(decision.selected.decode_tokens_per_second, 80.0)
        self.assertTrue(any("insufficient_decode_throughput" in candidate.reasons for candidate in decision.candidates if candidate.node_id == "node_slow"))

    def test_explicit_preferred_node_is_selected_deterministically(self) -> None:
        nodes = (
            _node("node_a", models=({"id": "qwen", "decode_tokens_per_second": 90},)),
            _node("node_b", models=({"id": "qwen", "decode_tokens_per_second": 20},)),
        )
        decision = CapabilityAwareNodeRouter().route(
            nodes,
            NodeRouteRequirement(model_id="qwen", preferred_node_ids=("node_b",)),
        )
        self.assertEqual(decision.selected.node_id, "node_b")
        self.assertTrue(decision.selected.preferred)


if __name__ == "__main__":
    unittest.main()
