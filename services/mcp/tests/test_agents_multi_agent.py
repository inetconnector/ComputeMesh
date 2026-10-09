"""Tests for bounded durable subagent fan-out and fan-in."""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from services.mcp.platform.leases import LeaseState, NodeLeaseStore
from services.mcp.platform.multi_agent import DelegationDenied, SubagentCoordinator
from services.mcp.platform.node_registry import NodeRegistry
from services.mcp.platform.session import AgentSessionStore, TurnStatus
from services.mcp.platform.subagents import SubagentContract, SubagentResult


class TestSubagentCoordinator(unittest.TestCase):
    @staticmethod
    def _ready_node(registry: NodeRegistry) -> None:
        registry.discover("node_1", "http://node:8080")
        registry.mark_reachable("node_1")
        registry.record_capabilities("node_1", capabilities=("inference",), models=({"id": "qwen"},), profile_revision=1)
        registry.verify_identity("node_1", identity_key_id="key_1", evidence_digest="a" * 64)
        registry.mark_authenticated("node_1", principal_id="provider_1")
        registry.mark_prepared("node_1", preparation_digest="b" * 64)
        registry.record_benchmark("node_1", accepted=True, metrics={"ok": True})

    def test_parallel_children_have_durable_sessions_and_fan_in(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = AgentSessionStore(Path(directory) / "sessions.sqlite3")
            try:
                parent = store.create_session("parent", principal_id="user_1")
                parent_turn = store.start_turn(parent.session_id, "delegate")
                contracts = [
                    SubagentContract.create(f"task {index}", expected_output="text", max_steps=2)
                    for index in range(2)
                ]
                coordinator = SubagentCoordinator(store, workspace_root=directory, max_total_steps=4)

                def runner(contract, session, turn):
                    return SubagentResult(contract.contract_id, "COMPLETED", contract.task.upper(), 1, (), ())

                batch = coordinator.delegate(parent.session_id, parent_turn.turn_id, contracts, runner)
                self.assertEqual(len(batch.executions), 2)
                self.assertEqual(len(batch.completed), 2)
                self.assertEqual(store.get_turn(parent_turn.turn_id).status, TurnStatus.RUNNING)
                for execution in batch.executions:
                    self.assertEqual(execution.turn.status, TurnStatus.COMPLETED)
                    self.assertEqual(execution.session.state["parent_session_id"], parent.session_id)
                event_types = [event.event_type for event in store.list_events(parent.session_id)]
                self.assertIn("subagents.completed", event_types)
            finally:
                store.close()

    def test_fanout_and_step_limits_fail_before_children(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = AgentSessionStore(Path(directory) / "sessions.sqlite3")
            try:
                parent = store.create_session("parent")
                parent_turn = store.start_turn(parent.session_id, "delegate")
                contracts = [SubagentContract.create("work", expected_output="text", max_steps=3) for _ in range(2)]
                coordinator = SubagentCoordinator(store, workspace_root=directory, max_children=1)
                with self.assertRaises(DelegationDenied):
                    coordinator.delegate(parent.session_id, parent_turn.turn_id, contracts, lambda *_: None)
                self.assertEqual(store.get_turn(parent_turn.turn_id).status, TurnStatus.QUEUED)
            finally:
                store.close()

    def test_children_use_and_release_session_bound_leases(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = AgentSessionStore(Path(directory) / "sessions.sqlite3")
            registry = NodeRegistry(Path(directory) / "nodes.sqlite3")
            lease_store = NodeLeaseStore(Path(directory) / "leases.sqlite3", node_registry=registry)
            try:
                self._ready_node(registry)
                parent = store.create_session("parent", principal_id="user_1")
                parent_turn = store.start_turn(parent.session_id, "delegate")

                def acquire(contract, session, turn):
                    return lease_store.reserve(
                        node_id="node_1",
                        session_id=session.session_id,
                        turn_id=turn.turn_id,
                        model_id="qwen",
                        idempotency_key=f"subagent_{contract.contract_id}",
                    )

                coordinator = SubagentCoordinator(
                    store,
                    workspace_root=directory,
                    lease_store=lease_store,
                    lease_factory=acquire,
                )
                contract = SubagentContract.create("leased work", expected_output="text", max_steps=2)
                batch = coordinator.delegate(
                    parent.session_id,
                    parent_turn.turn_id,
                    (contract,),
                    lambda item, *_: SubagentResult(item.contract_id, "COMPLETED", "ok", 1, (), ()),
                )
                execution = batch.executions[0]
                self.assertIsNotNone(execution.lease)
                self.assertEqual(execution.lease.status, LeaseState.RELEASED)
                self.assertEqual(lease_store.active_for_node("node_1"), ())
                events = [event.event_type for event in store.list_events(execution.session.session_id)]
                self.assertIn("subagent.lease.bound", events)
                self.assertIn("subagent.lease.released", events)
            finally:
                lease_store.close()
                registry.close()
                store.close()

    def test_failed_child_also_releases_its_lease(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = AgentSessionStore(Path(directory) / "sessions.sqlite3")
            registry = NodeRegistry(Path(directory) / "nodes.sqlite3")
            lease_store = NodeLeaseStore(Path(directory) / "leases.sqlite3", node_registry=registry)
            try:
                self._ready_node(registry)
                parent = store.create_session("parent")
                parent_turn = store.start_turn(parent.session_id, "delegate")

                def acquire(contract, session, turn):
                    return lease_store.reserve(
                        node_id="node_1",
                        session_id=session.session_id,
                        turn_id=turn.turn_id,
                        model_id="qwen",
                        idempotency_key=f"subagent_{contract.contract_id}",
                    )

                coordinator = SubagentCoordinator(
                    store,
                    workspace_root=directory,
                    lease_store=lease_store,
                    lease_factory=acquire,
                )
                contract = SubagentContract.create("failing work", expected_output="text")

                def fail(*_args):
                    raise RuntimeError("provider stopped")

                execution = coordinator.delegate(
                    parent.session_id,
                    parent_turn.turn_id,
                    (contract,),
                    fail,
                ).executions[0]
                self.assertEqual(execution.result.status, "FAILED")
                self.assertEqual(execution.turn.status, TurnStatus.FAILED)
                self.assertEqual(execution.lease.status, LeaseState.RELEASED)
                self.assertEqual(lease_store.active_for_node("node_1"), ())
            finally:
                lease_store.close()
                registry.close()
                store.close()


if __name__ == "__main__":
    unittest.main()
