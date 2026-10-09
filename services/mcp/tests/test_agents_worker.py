"""Tests for durable queued/resumed agent turn pickup."""
from __future__ import annotations

import sqlite3
import tempfile
import time
import unittest
from pathlib import Path

from services.gateway.inference_backend import SyntheticInferenceBackend
from services.mcp.agent_loop import AgentExecutionResult, AgentLoop
from services.mcp.config import MCPConfig
from services.mcp.platform.contracts import SideEffectLevel, ToolManifest
from services.mcp.platform.harness import MeshAgentHarness
from services.mcp.platform.model_caller import make_backend_model_caller
from services.mcp.platform.session import (
    AgentSessionStore,
    ApprovalStatus,
    SessionStatus,
    TurnStatus,
)
from services.mcp.platform.tool_broker import AgentToolBroker
from services.mcp.platform.tool_execution import SafeToolExecutor, ToolCapabilityRegistry
from services.mcp.platform.worker import (
    AgentWorkerRequest,
    DurableWorkerConcurrencyGate,
    MeshAgentWorker,
    MeshAgentWorkerService,
    WorkerConcurrencyBudget,
    WorkerConcurrencyGate,
    WorkerSchedulingPolicy,
)
from services.mcp.tool_registry import ToolRegistry


class _Loop:
    def run(self, messages, model, llm_caller, **kwargs):
        response = llm_caller(messages, [])
        content = str(response["choices"][0]["message"].get("content") or "")
        return AgentExecutionResult(
            final_content=content,
            messages=[*messages, {"role": "assistant", "content": content}],
            model=model,
            iterations=1,
        )


class _StopAfterWait:
    def __init__(self) -> None:
        self.stopped = False

    def is_set(self) -> bool:
        return self.stopped

    def wait(self, _timeout: float) -> None:
        self.stopped = True


class _WriteTool:
    def __init__(self) -> None:
        self.calls = 0

    def execute_tool(self, _name, arguments, is_owner=True, owner_id=None):
        self.calls += 1
        return {"ok": True, **arguments}


class TestMeshAgentWorker(unittest.TestCase):
    def test_concurrency_gate_enforces_global_principal_and_session_limits(self):
        gate = WorkerConcurrencyGate(WorkerConcurrencyBudget(global_limit=2, principal_limit=1, session_limit=1))
        self.assertTrue(gate.try_acquire(principal_id="principal_a", session_id="session_a"))
        self.assertFalse(gate.try_acquire(principal_id="principal_a", session_id="session_b"))
        self.assertTrue(gate.try_acquire(principal_id="principal_b", session_id="session_b"))
        self.assertFalse(gate.try_acquire(principal_id="principal_c", session_id="session_c"))
        gate.release(principal_id="principal_a", session_id="session_a")
        self.assertTrue(gate.try_acquire(principal_id="principal_a", session_id="session_c"))
        self.assertEqual(gate.snapshot()["active_global"], 2)

    def test_concurrency_gate_enforces_tenant_limit(self):
        gate = WorkerConcurrencyGate(
            WorkerConcurrencyBudget(
                global_limit=3,
                principal_limit=2,
                session_limit=1,
                tenant_limit=1,
            )
        )
        self.assertTrue(gate.try_acquire(
            principal_id="principal_a",
            session_id="session_a",
            admission_key="tenant:one",
            tenant_id="tenant_1",
        ))
        self.assertFalse(gate.try_acquire(
            principal_id="principal_b",
            session_id="session_b",
            admission_key="tenant:two",
            tenant_id="tenant_1",
        ))
        self.assertTrue(gate.try_acquire(
            principal_id="principal_b",
            session_id="session_b",
            admission_key="tenant:three",
            tenant_id="tenant_2",
        ))
        gate.release(
            principal_id="principal_a",
            session_id="session_a",
            admission_key="tenant:one",
        )
        self.assertEqual(gate.snapshot()["active_tenants"], {"tenant_2": 1})

    def test_durable_concurrency_gate_enforces_tenant_limit(self):
        with tempfile.TemporaryDirectory() as directory:
            gate = DurableWorkerConcurrencyGate(
                Path(directory) / "sessions.sqlite3",
                WorkerConcurrencyBudget(global_limit=3, principal_limit=2, session_limit=1, tenant_limit=1),
            )
            try:
                self.assertTrue(gate.try_acquire(
                    principal_id="principal_a",
                    session_id="session_a",
                    admission_key="tenant:one",
                    tenant_id="tenant_1",
                ))
                self.assertFalse(gate.try_acquire(
                    principal_id="principal_b",
                    session_id="session_b",
                    admission_key="tenant:two",
                    tenant_id="tenant_1",
                ))
                self.assertTrue(gate.try_acquire(
                    principal_id="principal_b",
                    session_id="session_b",
                    admission_key="tenant:three",
                    tenant_id="tenant_2",
                ))
                self.assertEqual(gate.snapshot()["active_tenants"], {"tenant_1": 1, "tenant_2": 1})
                gate.release(
                    principal_id="principal_a",
                    session_id="session_a",
                    admission_key="tenant:one",
                    tenant_id="tenant_1",
                )
            finally:
                gate.close()

    def test_durable_concurrency_gate_migrates_legacy_admission_table(self):
        with tempfile.TemporaryDirectory() as directory:
            database = Path(directory) / "legacy-admissions.sqlite3"
            connection = sqlite3.connect(database)
            connection.execute(
                """CREATE TABLE agent_worker_admissions (
                    admission_id TEXT PRIMARY KEY,
                    admission_key TEXT NOT NULL,
                    worker_id TEXT NOT NULL,
                    principal_id TEXT NOT NULL,
                    session_id TEXT NOT NULL,
                    acquired_at REAL NOT NULL,
                    heartbeat_at REAL NOT NULL,
                    expires_at REAL NOT NULL,
                    released_at REAL
                )"""
            )
            connection.commit()
            connection.close()
            gate = DurableWorkerConcurrencyGate(database)
            try:
                self.assertTrue(gate.try_acquire(
                    principal_id="principal_a",
                    session_id="session_a",
                    admission_key="legacy:one",
                ))
                columns = {
                    row["name"]
                    for row in gate._connection.execute("PRAGMA table_info(agent_worker_admissions)").fetchall()
                }
                self.assertIn("tenant_id", columns)
            finally:
                gate.close()

    def test_durable_concurrency_gate_coordinates_process_databases(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "sessions.sqlite3"
            first = DurableWorkerConcurrencyGate(
                path,
                WorkerConcurrencyBudget(global_limit=1, principal_limit=1, session_limit=1),
            )
            second = DurableWorkerConcurrencyGate(
                path,
                WorkerConcurrencyBudget(global_limit=1, principal_limit=1, session_limit=1),
            )
            try:
                self.assertTrue(first.try_acquire(
                    principal_id="principal_a",
                    session_id="session_a",
                    admission_key="worker_a:turn_a",
                    worker_id="worker_a",
                ))
                self.assertFalse(second.try_acquire(
                    principal_id="principal_b",
                    session_id="session_b",
                    admission_key="worker_b:turn_b",
                    worker_id="worker_b",
                ))
                self.assertTrue(first.renew(admission_key="worker_a:turn_a"))
                first.release(
                    principal_id="principal_a",
                    session_id="session_a",
                    admission_key="worker_a:turn_a",
                )
                self.assertTrue(second.try_acquire(
                    principal_id="principal_b",
                    session_id="session_b",
                    admission_key="worker_b:turn_b",
                    worker_id="worker_b",
                ))
                self.assertEqual(second.snapshot()["active_global"], 1)
            finally:
                first.close()
                second.close()

    def test_durable_concurrency_gate_reclaims_expired_lease(self):
        with tempfile.TemporaryDirectory() as directory:
            now = [100.0]
            gate = DurableWorkerConcurrencyGate(
                Path(directory) / "sessions.sqlite3",
                WorkerConcurrencyBudget(global_limit=1, principal_limit=1, session_limit=1),
                lease_seconds=1.0,
                clock=lambda: now[0],
            )
            try:
                self.assertTrue(gate.try_acquire(
                    principal_id="principal_a",
                    session_id="session_a",
                    admission_key="worker_a:turn_a",
                ))
                now[0] = 102.0
                self.assertTrue(gate.try_acquire(
                    principal_id="principal_b",
                    session_id="session_b",
                    admission_key="worker_b:turn_b",
                ))
                self.assertEqual(gate.snapshot()["active_global"], 1)
            finally:
                gate.close()

    def test_worker_service_can_enable_persistent_gate_with_default_budget(self):
        with tempfile.TemporaryDirectory() as directory:
            store = AgentSessionStore(Path(directory) / "sessions.sqlite3")
            try:
                service = MeshAgentWorkerService(
                    store,
                    worker_factory=lambda _worker_id: self._worker(store, []),
                    persistent_concurrency=True,
                )
                self.assertIsInstance(service.concurrency_gate, DurableWorkerConcurrencyGate)
                self.assertTrue(service.close())
            finally:
                store.close()

    def test_worker_resumes_approved_tool_and_finishes_model_synthesis(self):
        with tempfile.TemporaryDirectory() as directory:
            store = AgentSessionStore(Path(directory) / "sessions.sqlite3")
            try:
                session = store.create_session("agent", principal_id="principal_a")
                turn = store.start_turn(session.session_id, "write something")
                backend = _WriteTool()
                capabilities = ToolCapabilityRegistry()
                capabilities.register(ToolManifest(
                    "write_tool",
                    "write_tool",
                    side_effect=SideEffectLevel.WRITE_REVERSIBLE,
                    confirmation_required=True,
                ))
                registry = ToolRegistry(MCPConfig(max_agent_iterations=3))
                registry.register_tool("write_tool", "write tool", {"type": "object"}, lambda **_: {"ok": True})
                loop = AgentLoop(registry=registry, config=MCPConfig(max_agent_iterations=3))
                caller_count = {"value": 0}

                def caller(messages, tools):
                    caller_count["value"] += 1
                    if caller_count["value"] < 3:
                        return {"choices": [{"message": {"tool_calls": [{
                            "id": "call_write",
                            "type": "function",
                            "function": {"name": "write_tool", "arguments": "{\"value\":\"x\"}"},
                        }]}}]}
                    return {"choices": [{"message": {"content": "write completed"}}]}

                def harness_factory(_session, _turn, approved_ids):
                    def broker_factory(session_id, turn_id, resume_ids):
                        return AgentToolBroker(
                            SafeToolExecutor(backend, capabilities),
                            session_store=store,
                            session_id=session_id,
                            turn_id=turn_id,
                            owner_id="principal_a",
                            approved_approval_ids=tuple(resume_ids),
                        )

                    return MeshAgentHarness(
                        store,
                        agent_loop=loop,
                        tool_broker_factory=broker_factory,
                        approved_approval_ids=approved_ids,
                    )

                worker = MeshAgentWorker(
                    store,
                    harness_factory=harness_factory,
                    request_resolver=lambda _session, _turn: AgentWorkerRequest(
                        model="demo-model",
                        llm_caller=caller,
                        principal_id="principal_a",
                    ),
                    worker_id="worker_approval",
                )
                first = worker.run_once()[0]
                self.assertEqual(first.status, TurnStatus.WAITING_FOR_APPROVAL)
                self.assertEqual(backend.calls, 0)
                approval = store.list_approvals(session_id=session.session_id)[0]
                store.resolve_approval(
                    approval.approval_id,
                    principal_id="principal_a",
                    decision=ApprovalStatus.APPROVED,
                )
                store.resume_approved_turn(approval.approval_id)
                second = worker.run_once()[0]
                self.assertEqual(second.status, TurnStatus.COMPLETED)
                self.assertEqual(second.execution.execution.final_content, "write completed")
                self.assertEqual(backend.calls, 1)
                self.assertEqual(store.get_approval(approval.approval_id).status, ApprovalStatus.CONSUMED)
                self.assertGreaterEqual(caller_count["value"], 3)
            finally:
                store.close()

    def _worker(self, store, seen, *, failing_resolver=False):
        def harness_factory(session, turn, approved_ids):
            seen.append((session.session_id, turn.turn_id, approved_ids))
            return MeshAgentHarness(store, agent_loop=_Loop())

        def resolver(session, turn):
            if failing_resolver:
                raise RuntimeError("resolver unavailable")
            return AgentWorkerRequest(
                model=str(session.state.get("model") or "demo-model"),
                llm_caller=lambda messages, tools: {"choices": [{"message": {"content": "done"}}]},
            )

        return MeshAgentWorker(
            store,
            harness_factory=harness_factory,
            request_resolver=resolver,
            worker_id="worker_test",
        )

    def test_worker_claims_and_completes_queued_turn(self):
        with tempfile.TemporaryDirectory() as directory:
            store = AgentSessionStore(Path(directory) / "sessions.sqlite3")
            try:
                session = store.create_session("agent", state={"model": "demo-model"})
                turn = store.start_turn(session.session_id, "hello")
                seen = []
                results = self._worker(store, seen).run_once()
                self.assertEqual(len(results), 1)
                self.assertEqual(results[0].status, TurnStatus.COMPLETED)
                self.assertEqual(store.get_session(session.session_id).status, SessionStatus.READY)
                self.assertEqual(seen, [(session.session_id, turn.turn_id, ())])
                self.assertIn("turn.claimed", [event.event_type for event in store.list_events(session.session_id)])
            finally:
                store.close()

    def test_worker_preflight_keeps_unready_turn_queued(self):
        with tempfile.TemporaryDirectory() as directory:
            store = AgentSessionStore(Path(directory) / "sessions.sqlite3")
            try:
                session = store.create_session("agent", state={"model": "mesh-model"})
                turn = store.start_turn(session.session_id, "wait for a capable provider")
                available = {"value": False}
                worker = MeshAgentWorker(
                    store,
                    harness_factory=lambda _session, _turn, _approved: MeshAgentHarness(store, agent_loop=_Loop()),
                    request_resolver=lambda _session, _turn: AgentWorkerRequest(
                        model="mesh-model",
                        llm_caller=lambda messages, tools: {"choices": [{"message": {"content": "done"}}]},
                    ),
                    worker_id="worker_preflight",
                    preflight=lambda _session, _turn: available["value"],
                )
                self.assertEqual(worker.run_once(), ())
                self.assertEqual(store.get_turn(turn.turn_id).status, TurnStatus.QUEUED)
                available["value"] = True
                result = worker.run_once()
                self.assertEqual(result[0].status, TurnStatus.COMPLETED)
                self.assertEqual(store.get_turn(turn.turn_id).status, TurnStatus.COMPLETED)
            finally:
                store.close()

    def test_worker_honors_persisted_priority_before_fifo(self):
        with tempfile.TemporaryDirectory() as directory:
            store = AgentSessionStore(Path(directory) / "sessions.sqlite3")
            try:
                low_session = store.create_session("agent", principal_id="principal_low")
                low_turn = store.start_turn(low_session.session_id, "low", priority=1)
                high_session = store.create_session("agent", principal_id="principal_high")
                high_turn = store.start_turn(high_session.session_id, "high", priority=9)
                seen = []
                result = self._worker(store, seen).run_once(limit=1)[0]
                self.assertEqual(result.turn_id, high_turn.turn_id)
                self.assertNotEqual(result.turn_id, low_turn.turn_id)
                self.assertEqual(seen[0][0], high_session.session_id)
            finally:
                store.close()

    def test_worker_rotates_equal_priority_principals(self):
        with tempfile.TemporaryDirectory() as directory:
            store = AgentSessionStore(Path(directory) / "sessions.sqlite3")
            try:
                first = store.create_session("agent", principal_id="principal_a")
                first_turn = store.start_turn(first.session_id, "a", priority=3)
                second = store.create_session("agent", principal_id="principal_b")
                second_turn = store.start_turn(second.session_id, "b", priority=3)
                seen = []
                results = self._worker(store, seen).run_once(limit=2)
                self.assertEqual([result.turn_id for result in results], [first_turn.turn_id, second_turn.turn_id])
                self.assertEqual([entry[0] for entry in seen], [first.session_id, second.session_id])
            finally:
                store.close()

    def test_worker_expires_queued_turn_before_execution(self):
        with tempfile.TemporaryDirectory() as directory:
            store = AgentSessionStore(Path(directory) / "sessions.sqlite3")
            try:
                session = store.create_session("agent", principal_id="principal_a")
                turn = store.start_turn(session.session_id, "expired", deadline_at=time.time() - 1.0)
                seen = []
                result = self._worker(store, seen).run_once()[0]
                self.assertFalse(result.claimed)
                self.assertEqual(result.error_type, "DeadlineExceeded")
                self.assertEqual(result.status, TurnStatus.FAILED)
                self.assertEqual(store.get_turn(turn.turn_id).error, "deadline_exceeded")
                self.assertEqual(seen, [])
                self.assertIn(
                    "turn.status_changed",
                    [event.event_type for event in store.list_events(session.session_id)],
                )
            finally:
                store.close()

    def test_worker_scheduling_policy_rejects_unbounded_values(self):
        with self.assertRaises(ValueError):
            WorkerSchedulingPolicy(aging_interval_seconds=0.5)
        with self.assertRaises(ValueError):
            WorkerSchedulingPolicy(max_candidates=5001)

    def test_worker_passes_only_approved_ids_for_resumed_turn(self):
        with tempfile.TemporaryDirectory() as directory:
            store = AgentSessionStore(Path(directory) / "sessions.sqlite3")
            try:
                session = store.create_session("agent", principal_id="principal_a", state={"model": "demo-model"})
                turn = store.start_turn(session.session_id, "write")
                store.transition_turn(turn.turn_id, TurnStatus.RUNNING)
                store.transition_turn(turn.turn_id, TurnStatus.WAITING_FOR_APPROVAL)
                approval = store.create_approval(
                    session.session_id,
                    turn_id=turn.turn_id,
                    tool_id="write_tool",
                    call_id="call_1",
                    arguments_digest="a" * 64,
                    principal_id="principal_a",
                )
                store.resolve_approval(approval.approval_id, principal_id="principal_a", decision=ApprovalStatus.APPROVED)
                store.resume_approved_turn(approval.approval_id)
                seen = []
                results = self._worker(store, seen).run_once()
                self.assertEqual(results[0].status, TurnStatus.COMPLETED)
                self.assertEqual(seen[0][2], (approval.approval_id,))
            finally:
                store.close()

    def test_only_one_worker_can_claim_a_turn(self):
        with tempfile.TemporaryDirectory() as directory:
            store = AgentSessionStore(Path(directory) / "sessions.sqlite3")
            try:
                session = store.create_session("agent")
                turn = store.start_turn(session.session_id, "hello")
                claimed = store.claim_turn(turn.turn_id, worker_id="worker_a")
                self.assertIsNotNone(claimed)
                self.assertIsNone(store.claim_turn(turn.turn_id, worker_id="worker_b"))
            finally:
                store.close()

    def test_resolver_failure_fails_claimed_turn_without_replay(self):
        with tempfile.TemporaryDirectory() as directory:
            store = AgentSessionStore(Path(directory) / "sessions.sqlite3")
            try:
                session = store.create_session("agent")
                turn = store.start_turn(session.session_id, "hello")
                seen = []
                result = self._worker(store, seen, failing_resolver=True).run_once()[0]
                self.assertEqual(result.status, TurnStatus.FAILED)
                self.assertEqual(store.get_turn(turn.turn_id).status, TurnStatus.FAILED)
                self.assertEqual(self._worker(store, []).run_once(), ())
            finally:
                store.close()

    def test_worker_runs_existing_synthetic_backend_through_real_harness(self):
        with tempfile.TemporaryDirectory() as directory:
            store = AgentSessionStore(Path(directory) / "sessions.sqlite3")
            try:
                session, turn = store.create_task(
                    "mesh.agent",
                    "demo-model",
                    "hello",
                    principal_id="principal_a",
                )
                caller = make_backend_model_caller(SyntheticInferenceBackend(), model_id="demo-model")
                worker = MeshAgentWorker(
                    store,
                    harness_factory=lambda _session, _turn, _approval_ids: MeshAgentHarness(store),
                    request_resolver=lambda _session, _turn: AgentWorkerRequest(
                        model="demo-model",
                        llm_caller=caller,
                    ),
                    worker_id="worker_backend",
                )
                result = worker.run_once()[0]
                self.assertEqual(result.status, TurnStatus.COMPLETED)
                self.assertIn("ComputeMesh", result.execution.execution.final_content)
                self.assertEqual(store.get_turn(turn.turn_id).status, TurnStatus.COMPLETED)
            finally:
                store.close()

    def test_worker_loop_waits_without_work_and_stops_cleanly(self):
        with tempfile.TemporaryDirectory() as directory:
            store = AgentSessionStore(Path(directory) / "sessions.sqlite3")
            try:
                stop = _StopAfterWait()
                worker = self._worker(store, [])
                self.assertEqual(worker.run_until_stopped(stop, poll_interval=0.01), ())
                self.assertTrue(stop.stopped)
            finally:
                store.close()

    def test_supervised_service_recovers_active_turns_without_replaying_them(self):
        with tempfile.TemporaryDirectory() as directory:
            store = AgentSessionStore(Path(directory) / "sessions.sqlite3")
            try:
                session, turn = store.create_task(
                    "mesh.agent",
                    "demo-model",
                    "hello",
                    principal_id="principal_a",
                )
                self.assertIsNotNone(store.claim_turn(turn.turn_id, worker_id="old-worker"))
                worker = self._worker(store, [])
                service = MeshAgentWorkerService(
                    store,
                    worker_factory=lambda worker_id: MeshAgentWorker(
                        store,
                        harness_factory=worker.harness_factory,
                        request_resolver=worker.request_resolver,
                        worker_id=worker_id,
                    ),
                    recover_on_start=True,
                )
                snapshot = service.start()
                self.assertEqual(snapshot.recovered_turn_ids, (turn.turn_id,))
                self.assertEqual(store.get_turn(turn.turn_id).status, TurnStatus.PAUSED)
                self.assertTrue(service.close(timeout=2.0))
                self.assertEqual(service.snapshot().result_count, 0)
                self.assertEqual(store.get_session(session.session_id).status, SessionStatus.PAUSED)
            finally:
                store.close()

    def test_supervised_service_picks_up_work_and_stops(self):
        with tempfile.TemporaryDirectory() as directory:
            store = AgentSessionStore(Path(directory) / "sessions.sqlite3")
            try:
                session = store.create_session("agent", state={"model": "demo-model"})
                turn = store.start_turn(session.session_id, "hello")
                base_worker = self._worker(store, [])
                service = MeshAgentWorkerService(
                    store,
                    worker_factory=lambda worker_id: MeshAgentWorker(
                        store,
                        harness_factory=base_worker.harness_factory,
                        request_resolver=base_worker.request_resolver,
                        worker_id=worker_id,
                    ),
                    poll_interval=0.01,
                )
                service.start()
                deadline = time.monotonic() + 2.0
                while store.get_turn(turn.turn_id).status is not TurnStatus.COMPLETED and time.monotonic() < deadline:
                    time.sleep(0.01)
                self.assertEqual(store.get_turn(turn.turn_id).status, TurnStatus.COMPLETED)
                self.assertTrue(service.close(timeout=2.0))
                self.assertEqual(service.snapshot().error_count, 0)
                self.assertEqual(len(service.results()), 1)
            finally:
                store.close()


if __name__ == "__main__":
    unittest.main()
