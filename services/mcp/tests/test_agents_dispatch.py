"""Tests for lease-bound capability routing and model dispatch."""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from services.mcp.platform.dispatch import (
    LeaseBoundModelDispatcher,
    ModelDispatchError,
    NoCapableNode,
)
from services.mcp.platform.leases import NodeLeaseStore
from services.mcp.platform.node_registry import NodeRegistry
from services.mcp.platform.node_routing import NodeRouteRequirement


class TestLeaseBoundModelDispatcher(unittest.TestCase):
    def _ready(self, registry: NodeRegistry, node_id: str = "node_1") -> None:
        registry.discover(node_id, f"tls://{node_id}")
        registry.mark_reachable(node_id)
        registry.record_capabilities(
            node_id,
            capabilities=("inference",),
            models=({"id": "qwen", "context_tokens": 32768, "free_vram_bytes": 16_000_000_000},),
            profile_revision=1,
        )
        registry.verify_identity(node_id, identity_key_id=f"key_{node_id}", evidence_digest="a" * 64)
        registry.mark_authenticated(node_id, principal_id=f"provider_{node_id}")
        registry.mark_prepared(node_id, preparation_digest="b" * 64)
        registry.record_benchmark(node_id, accepted=True, metrics={"decode": 30})

    def test_dispatch_reserves_and_releases_capacity(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            registry = NodeRegistry(Path(directory) / "nodes.sqlite3")
            leases = NodeLeaseStore(Path(directory) / "leases.sqlite3", node_registry=registry)
            try:
                self._ready(registry)
                events = []
                calls = []
                dispatcher = LeaseBoundModelDispatcher(
                    registry,
                    leases,
                    lambda node, payload: calls.append(1) or {"node_id": node.node_id, "model": payload["model"], "text": "ok"},
                    event_sink=lambda event, payload: events.append((event, payload)),
                )
                result = dispatcher.dispatch(
                    session_id="sess_1",
                    turn_id="turn_1",
                    model_id="qwen",
                    requirement=NodeRouteRequirement(model_id="qwen", required_capabilities=frozenset({"inference"})),
                    payload={"model": "qwen", "prompt": "hello"},
                    idempotency_key="dispatch_1",
                )
                self.assertEqual(result.response["text"], "ok")
                with self.assertRaises(ModelDispatchError):
                    dispatcher.dispatch(
                        session_id="sess_1",
                        turn_id="turn_1",
                        model_id="qwen",
                        requirement=NodeRouteRequirement(model_id="qwen", required_capabilities=frozenset({"inference"})),
                        payload={"model": "qwen", "prompt": "hello"},
                        idempotency_key="dispatch_1",
                    )
                self.assertEqual(calls, [1])
                self.assertEqual(leases.active_for_node("node_1"), ())
                self.assertEqual([event for event, _ in events], ["mesh.dispatch.started", "mesh.dispatch.completed"])
            finally:
                leases.close()
                registry.close()

    def test_binding_failure_still_releases_lease(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            registry = NodeRegistry(Path(directory) / "nodes.sqlite3")
            leases = NodeLeaseStore(Path(directory) / "leases.sqlite3", node_registry=registry)
            try:
                self._ready(registry)
                dispatcher = LeaseBoundModelDispatcher(registry, leases, lambda node, payload: {"node_id": "other"})
                with self.assertRaises(ModelDispatchError):
                    dispatcher.dispatch(
                        session_id="sess_1",
                        turn_id="turn_1",
                        model_id="qwen",
                        requirement=NodeRouteRequirement(model_id="qwen"),
                        payload={"model": "qwen"},
                        idempotency_key="dispatch_1",
                    )
                self.assertEqual(leases.active_for_node("node_1"), ())
            finally:
                leases.close()
                registry.close()

    def test_unroutable_model_fails_before_lease(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            registry = NodeRegistry(Path(directory) / "nodes.sqlite3")
            leases = NodeLeaseStore(Path(directory) / "leases.sqlite3", node_registry=registry)
            try:
                self._ready(registry)
                dispatcher = LeaseBoundModelDispatcher(registry, leases, lambda node, payload: {})
                with self.assertRaises(NoCapableNode):
                    dispatcher.dispatch(
                        session_id="sess_1",
                        turn_id="turn_1",
                        model_id="missing",
                        requirement=NodeRouteRequirement(model_id="missing"),
                        payload={"model": "missing"},
                        idempotency_key="dispatch_1",
                    )
                self.assertEqual(leases.active_for_node("node_1"), ())
            finally:
                leases.close()
                registry.close()

    def test_transient_provider_failure_falls_back_to_another_node(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            registry = NodeRegistry(Path(directory) / "nodes.sqlite3")
            leases = NodeLeaseStore(Path(directory) / "leases.sqlite3", node_registry=registry)
            try:
                self._ready(registry, "node_1")
                self._ready(registry, "node_2")
                events = []
                calls = []

                def execute(node, payload):
                    calls.append(node.node_id)
                    if node.node_id == "node_1":
                        raise ConnectionError("provider disconnected")
                    return {"node_id": node.node_id, "model": payload["model"], "text": "fallback"}

                dispatcher = LeaseBoundModelDispatcher(
                    registry,
                    leases,
                    execute,
                    event_sink=lambda event, payload: events.append((event, payload)),
                    max_attempts=2,
                )
                result = dispatcher.dispatch(
                    session_id="sess_1",
                    turn_id="turn_1",
                    model_id="qwen",
                    requirement=NodeRouteRequirement(model_id="qwen", required_capabilities=frozenset({"inference"})),
                    payload={"model": "qwen", "prompt": "hello"},
                    idempotency_key="dispatch_fallback",
                )
                self.assertEqual(result.node_id, "node_2")
                self.assertEqual(calls, ["node_1", "node_2"])
                self.assertIn("mesh.dispatch.retrying", [event for event, _ in events])
                self.assertEqual(leases.active_for_node("node_1"), ())
                self.assertEqual(leases.active_for_node("node_2"), ())
            finally:
                leases.close()
                registry.close()

    def test_busy_best_node_falls_back_without_consuming_execution_retry(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            registry = NodeRegistry(Path(directory) / "nodes.sqlite3")
            leases = NodeLeaseStore(Path(directory) / "leases.sqlite3", node_registry=registry)
            try:
                self._ready(registry, "node_1")
                self._ready(registry, "node_2")
                blocking = leases.reserve(
                    node_id="node_1",
                    session_id="other_session",
                    turn_id="other_turn",
                    model_id="qwen",
                    idempotency_key="blocking_lease",
                )
                events = []
                calls = []

                dispatcher = LeaseBoundModelDispatcher(
                    registry,
                    leases,
                    lambda node, payload: calls.append(node.node_id) or {
                        "node_id": node.node_id,
                        "model": payload["model"],
                        "text": "capacity fallback",
                    },
                    event_sink=lambda event, payload: events.append((event, payload)),
                    max_attempts=1,
                )
                result = dispatcher.dispatch(
                    session_id="sess_1",
                    turn_id="turn_1",
                    model_id="qwen",
                    requirement=NodeRouteRequirement(model_id="qwen", required_capabilities=frozenset({"inference"})),
                    payload={"model": "qwen", "prompt": "hello"},
                    idempotency_key="capacity_fallback",
                )
                self.assertEqual(result.node_id, "node_2")
                self.assertEqual(calls, ["node_2"])
                self.assertIn("mesh.dispatch.capacity_skipped", [event for event, _ in events])
                self.assertEqual(leases.get(blocking.lease_id).status.value, "active")
            finally:
                leases.close()
                registry.close()


if __name__ == "__main__":
    unittest.main()
