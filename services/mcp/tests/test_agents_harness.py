"""Tests for the durable adapter around the legacy AgentLoop."""
from __future__ import annotations

import tempfile
import threading
import time
import unittest
from pathlib import Path

from services.mcp.agent_loop import AgentExecutionResult, AgentLoop
from services.mcp.platform.context import ContextManager
from services.mcp.platform.contracts import RuntimePolicyEnvelope
from services.mcp.platform.harness import MeshAgentHarness
from services.mcp.platform.session import AgentSessionStore, SessionStatus, TurnStatus
from services.mcp.platform.tracing import TraceStore
from services.mcp.platform.usage import UsageLedger


class FakeAgentLoop:
    def run(self, messages, model, llm_caller, **kwargs):
        callback = kwargs.get("on_progress")
        if callback:
            callback({"event": "iteration_start", "iteration": 1, "max_iterations": 1, "secret": "ignored"})
        response = llm_caller(messages, [])
        return AgentExecutionResult(
            final_content=str(response["choices"][0]["message"]["content"]),
            messages=[
                *messages,
                {"role": "assistant", "content": str(response["choices"][0]["message"]["content"])},
            ],
            model=model,
            iterations=1,
            resource_usage={
                "gpu_milliseconds": 12,
                "vram_byte_seconds": 345,
                "network_bytes": 678,
                "external_cost_micros": 9,
            },
            provenance={
                "execution_job_ids": ["job-agent-1"],
                "execution_node_ids": ["node-agent-1", "node-agent-2"],
            },
        )


class _CheckpointToolBroker:
    def __init__(self) -> None:
        self.fail = True
        self.calls = 0

    def execute_tools_batch(self, tool_calls, *, is_owner=True):
        self.calls += 1
        if self.fail:
            raise RuntimeError("simulated worker interruption")
        return [
            {
                "id": str(call.get("id") or "call-1"),
                "name": str(call.get("function", {}).get("name") or "read_status"),
                "arguments": {},
                "result": {"ok": True},
            }
            for call in tool_calls
        ]


class TestMeshAgentHarness(unittest.TestCase):
    def test_cancel_control_interrupts_inflight_model_caller(self):
        with tempfile.TemporaryDirectory() as directory:
            store = AgentSessionStore(Path(directory) / "sessions.sqlite3")
            try:
                session = store.create_session("mesh.agent", principal_id="principal_a")
                turn = store.start_turn(session.session_id, "cancel the running task")
                started = threading.Event()

                def caller(messages, tools, *, cancel_event):
                    started.set()
                    self.assertTrue(cancel_event.wait(2))
                    raise RuntimeError("backend observed cancellation")

                def request_cancel() -> None:
                    self.assertTrue(started.wait(1))
                    store.request_control(
                        session.session_id,
                        "cancel",
                        principal_id="principal_a",
                        turn_id=turn.turn_id,
                    )

                cancel_thread = threading.Thread(target=request_cancel)
                cancel_thread.start()
                result = MeshAgentHarness(store, agent_loop=AgentLoop()).run_turn(
                    session.session_id,
                    turn.turn_id,
                    model="demo-model",
                    principal_id="principal_a",
                    llm_caller=caller,
                )
                cancel_thread.join(2)
                self.assertFalse(cancel_thread.is_alive())
                self.assertEqual(result.turn.status, TurnStatus.CANCELLED)
                self.assertEqual(result.control_action, "cancel")
            finally:
                store.close()

    def test_runtime_policy_is_revalidated_before_turn_execution(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = AgentSessionStore(Path(directory) / "sessions.sqlite3")
            try:
                session = store.create_session("mesh.agent", principal_id="principal_a")
                turn = store.start_turn(session.session_id, "must be denied after expiry")
                harness = MeshAgentHarness(
                    store,
                    agent_loop=FakeAgentLoop(),
                    runtime_policy=RuntimePolicyEnvelope(
                        decision_id="decision_expired",
                        request_id=f"agent-turn:{turn.turn_id}",
                        allow_agents=True,
                        principal_id="principal_a",
                        fleet_id="fleet-a",
                        expires_at=time.time() - 1,
                    ),
                )
                with self.assertRaises(PermissionError):
                    harness.run_turn(
                        session.session_id,
                        turn.turn_id,
                        model="demo-model",
                        principal_id="principal_a",
                        llm_caller=lambda messages, tools: {"choices": [{"message": {"content": "must not run"}}]},
                    )
                self.assertEqual(store.get_turn(turn.turn_id).status, TurnStatus.FAILED)
                self.assertTrue(
                    any(event.event_type == "runtime_policy.rejected" for event in store.list_events(session.session_id))
                )
            finally:
                store.close()

    def test_resume_reuses_inflight_model_checkpoint_without_repeating_model_call(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = AgentSessionStore(Path(directory) / "sessions.sqlite3")
            try:
                session = store.create_session("mesh.agent", principal_id="principal_a")
                turn = store.start_turn(session.session_id, "continue the task")
                broker = _CheckpointToolBroker()
                model_calls = []

                def caller(messages, tools):
                    model_calls.append([dict(message) for message in messages])
                    if len(model_calls) == 1:
                        return {
                            "choices": [{"message": {
                                "content": "",
                                "tool_calls": [{
                                    "id": "call-1",
                                    "type": "function",
                                    "function": {"name": "read_status", "arguments": "{}"},
                                }],
                            }}],
                            "usage": {"prompt_tokens": 3, "completion_tokens": 1},
                        }
                    return {
                        "choices": [{"message": {"content": "finished"}}],
                        "usage": {"prompt_tokens": 4, "completion_tokens": 2},
                    }

                harness = MeshAgentHarness(store, agent_loop=AgentLoop(), tool_broker=broker)
                with self.assertRaises(RuntimeError):
                    harness.run_turn(
                        session.session_id,
                        turn.turn_id,
                        model="demo-model",
                        principal_id="principal_a",
                        llm_caller=caller,
                    )
                checkpoint = store.get_turn_checkpoint(turn.turn_id)
                self.assertIsNotNone(checkpoint)
                self.assertEqual(checkpoint["phase"], "model_complete")
                self.assertEqual(len(model_calls), 1)

                store.request_control(
                    session.session_id,
                    "resume",
                    principal_id="principal_a",
                    turn_id=turn.turn_id,
                )
                broker.fail = False
                result = harness.run_turn(
                    session.session_id,
                    turn.turn_id,
                    model="demo-model",
                    principal_id="principal_a",
                    llm_caller=caller,
                )
                self.assertEqual(result.turn.status, TurnStatus.COMPLETED)
                self.assertEqual(result.execution.final_content, "finished")
                self.assertEqual(len(model_calls), 2)
                self.assertEqual(broker.calls, 2)
                self.assertIsNone(store.get_turn_checkpoint(turn.turn_id))
            finally:
                store.close()

    def test_successful_turn_is_accounted_once(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = AgentSessionStore(Path(directory) / "sessions.sqlite3")
            ledger = UsageLedger(Path(directory) / "usage.sqlite3")
            try:
                session = store.create_session("mesh.agent")
                turn = store.start_turn(session.session_id, "hello")
                harness = MeshAgentHarness(store, agent_loop=FakeAgentLoop(), usage_ledger=ledger)
                result = harness.run_turn(
                    session.session_id,
                    turn.turn_id,
                    model="demo-model",
                    principal_id="user_1",
                    llm_caller=lambda messages, tools: {
                        "choices": [{"message": {"content": "done"}}]
                    },
                )
                self.assertIsNotNone(result.usage_record)
                self.assertEqual(ledger.totals(session_id=session.session_id).tool_calls, 0)
                totals = ledger.totals(session_id=session.session_id)
                self.assertEqual(totals.gpu_milliseconds, 12)
                self.assertEqual(totals.vram_byte_seconds, 345)
                self.assertEqual(totals.network_bytes, 678)
                self.assertEqual(totals.external_cost_micros, 9)
                usage_event = next(event for event in store.list_events(session.session_id) if event.event_type == "usage.recorded")
                self.assertEqual(result.usage_record.delta.node_id, "node-agent-1")
                self.assertEqual(result.usage_record.delta.execution_job_ids, ("job-agent-1",))
                self.assertEqual(result.usage_record.delta.execution_node_ids, ("node-agent-1", "node-agent-2"))
                self.assertEqual(usage_event.payload["execution_job_ids"], ["job-agent-1"])
                self.assertEqual(usage_event.payload["execution_node_ids"], ["node-agent-1", "node-agent-2"])
            finally:
                ledger.close()
                store.close()

    def test_provenance_is_recorded_in_trace(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = AgentSessionStore(Path(directory) / "sessions.sqlite3")
            trace = TraceStore(Path(directory) / "trace.sqlite3")
            try:
                session = store.create_session("mesh.agent")
                turn = store.start_turn(session.session_id, "hello")
                harness = MeshAgentHarness(store, agent_loop=FakeAgentLoop(), trace_store=trace)
                harness.run_turn(
                    session.session_id,
                    turn.turn_id,
                    model="demo-model",
                    llm_caller=lambda messages, tools: {"choices": [{"message": {"content": "done"}}]},
                )
                root = next(span for span in trace.list_for_session(session.session_id) if span.kind == "turn")
                self.assertEqual(root.attributes["execution_job_ids"], "['job-agent-1']")
                self.assertEqual(root.attributes["execution_node_ids"], "['node-agent-1', 'node-agent-2']")
            finally:
                trace.close()
                store.close()

    def test_run_persists_context_progress_and_completion(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = AgentSessionStore(Path(directory) / "sessions.sqlite3")
            try:
                session = store.create_session("mesh.agent", agent_version="1")
                turn = store.start_turn(session.session_id, "hello")
                harness = MeshAgentHarness(store, agent_loop=FakeAgentLoop())
                result = harness.run_turn(
                    session.session_id,
                    turn.turn_id,
                    model="demo-model",
                    llm_caller=lambda messages, tools: {
                        "choices": [{"message": {"content": "done"}}]
                    },
                )
                self.assertEqual(result.session.status, SessionStatus.READY)
                self.assertEqual(result.turn.status, TurnStatus.COMPLETED)
                self.assertTrue(any(item.kind == "assistant" for item in store.list_items(session.session_id)))
                events = store.list_events(session.session_id)
                self.assertTrue(any(event.event_type == "context.built" for event in events))
                progress = [event for event in events if event.event_type == "turn.progress"]
                self.assertEqual(progress[0].payload["event"], "iteration_start")
                self.assertNotIn("secret", progress[0].payload)
            finally:
                store.close()

    def test_context_failure_marks_turn_failed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = AgentSessionStore(Path(directory) / "sessions.sqlite3")
            try:
                session = store.create_session("mesh.agent")
                turn = store.start_turn(session.session_id, "x" * 1000)
                harness = MeshAgentHarness(
                    store,
                    agent_loop=FakeAgentLoop(),
                    context_manager=ContextManager(max_tokens=10),
                )
                with self.assertRaises(ValueError):
                    harness.run_turn(
                        session.session_id,
                        turn.turn_id,
                        model="demo-model",
                        llm_caller=lambda messages, tools: {"choices": []},
                    )
                self.assertEqual(store.get_turn(turn.turn_id).status, TurnStatus.FAILED)
                self.assertEqual(store.get_session(session.session_id).status, SessionStatus.FAILED)
            finally:
                store.close()

    def test_context_compactor_is_checkpointed_and_reused(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = AgentSessionStore(Path(directory) / "sessions.sqlite3")
            try:
                session = store.create_session("mesh.agent")
                turn = store.start_turn(session.session_id, [
                    {"role": "user", "content": "x" * 1000},
                    {"role": "user", "content": "latest request"},
                ])
                summaries = []
                harness = MeshAgentHarness(
                    store,
                    agent_loop=FakeAgentLoop(),
                    context_manager=ContextManager(max_tokens=100),
                    context_compactor=lambda items: summaries.append(items) or "compact summary",
                )
                result = harness.run_turn(
                    session.session_id,
                    turn.turn_id,
                    model="demo-model",
                    llm_caller=lambda messages, tools: {"choices": [{"message": {"content": "done"}}]},
                )
                self.assertEqual(result.turn.status, TurnStatus.COMPLETED)
                self.assertEqual(store.get_session(session.session_id).state["checkpoint"]["context_summary"], "compact summary")
                self.assertEqual(len(summaries), 1)
                events = [event.event_type for event in store.list_events(session.session_id)]
                self.assertIn("context.compaction.started", events)
                self.assertIn("context.compaction.completed", events)
            finally:
                store.close()


if __name__ == "__main__":
    unittest.main()
