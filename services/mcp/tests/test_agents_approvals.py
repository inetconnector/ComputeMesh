# SPDX-License-Identifier: Apache-2.0
"""Tests for durable approval objects and broker integration."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from services.mcp.agent_loop import AgentApprovalRequired, AgentExecutionResult, AgentLoop
from services.mcp.config import MCPConfig
from services.mcp.platform.contracts import SideEffectLevel, ToolManifest
from services.mcp.platform.harness import MeshAgentHarness
from services.mcp.platform.session import (
    AgentSessionStore,
    ApprovalStatus,
    SessionStateConflict,
    SessionStatus,
    TurnStatus,
)
from services.mcp.platform.session_projection import project_approval, project_approvals
from services.mcp.platform.tool_broker import AgentToolBroker
from services.mcp.platform.tool_execution import SafeToolExecutor, ToolCapabilityRegistry
from services.mcp.tool_registry import ToolRegistry


class _WriteTool:
    def __init__(self) -> None:
        self.calls = 0

    def execute_tool(self, _name, arguments, is_owner=True, owner_id=None):
        self.calls += 1
        return {"ok": True, **arguments}


class TestAgentApprovals(unittest.TestCase):
    def test_approval_is_durable_principal_bound_and_single_resolution(self):
        with tempfile.TemporaryDirectory() as directory:
            store = AgentSessionStore(Path(directory) / "sessions.sqlite3")
            try:
                session = store.create_session("agent", principal_id="principal_a", session_id="sess_approval")
                turn = store.start_turn(session.session_id, "do it", turn_id="turn_approval")
                approval = store.create_approval(
                    session.session_id,
                    turn_id=turn.turn_id,
                    tool_id="write_tool",
                    call_id="call_1",
                    arguments_digest="a" * 64,
                    principal_id="principal_a",
                )
                duplicate = store.create_approval(
                    session.session_id,
                    turn_id=turn.turn_id,
                    tool_id="write_tool",
                    call_id="call_1",
                    arguments_digest="a" * 64,
                    principal_id="principal_a",
                )
                self.assertEqual(approval.approval_id, duplicate.approval_id)
                self.assertEqual(project_approvals(store, principal_id="principal_a")["approvals"][0]["status"], "pending")
                self.assertNotIn("principal_id", project_approval(store, approval.approval_id, principal_id="principal_a")["approval"])
                with self.assertRaises(PermissionError):
                    store.resolve_approval(approval.approval_id, principal_id="principal_b", decision=ApprovalStatus.APPROVED)
                resolved = store.resolve_approval(approval.approval_id, principal_id="principal_a", decision=ApprovalStatus.APPROVED, reason="confirmed")
                self.assertEqual(resolved.status, ApprovalStatus.APPROVED)
                with self.assertRaises(SessionStateConflict):
                    store.resolve_approval(approval.approval_id, principal_id="principal_a", decision=ApprovalStatus.REJECTED)
                self.assertTrue(any(event.event_type == "approval.granted" for event in store.list_events(session.session_id)))
            finally:
                store.close()

    def test_broker_persists_confirmation_without_executing_side_effect(self):
        with tempfile.TemporaryDirectory() as directory:
            store = AgentSessionStore(Path(directory) / "sessions.sqlite3")
            try:
                session = store.create_session("agent", principal_id="principal_a")
                turn = store.start_turn(session.session_id, "write")
                backend = _WriteTool()
                capabilities = ToolCapabilityRegistry()
                capabilities.register(ToolManifest(
                    "write_tool",
                    "write_tool",
                    side_effect=SideEffectLevel.WRITE_REVERSIBLE,
                    confirmation_required=True,
                    idempotent=False,
                ))
                broker = AgentToolBroker(
                    SafeToolExecutor(backend, capabilities),
                    session_store=store,
                    session_id=session.session_id,
                    turn_id=turn.turn_id,
                    owner_id="principal_a",
                )
                result = broker.execute_tool("write_tool", {"value": "x"}, call_id="call_write")
                self.assertEqual(result["status"], "confirmation_required")
                approval_id = result["provenance"]["approval_id"]
                self.assertTrue(approval_id)
                self.assertEqual(backend.calls, 0)
                approval = store.get_approval(approval_id)
                self.assertEqual(approval.tool_id, "write_tool")
                self.assertEqual(approval.status, ApprovalStatus.PENDING)
            finally:
                store.close()

    def test_batch_stops_after_first_pending_side_effect(self):
        with tempfile.TemporaryDirectory() as directory:
            store = AgentSessionStore(Path(directory) / "sessions.sqlite3")
            try:
                session = store.create_session("agent", principal_id="principal_a")
                turn = store.start_turn(session.session_id, "write")
                backend = _WriteTool()
                capabilities = ToolCapabilityRegistry()
                capabilities.register(ToolManifest(
                    "write_tool",
                    "write_tool",
                    side_effect=SideEffectLevel.WRITE_REVERSIBLE,
                    confirmation_required=True,
                ))
                broker = AgentToolBroker(
                    SafeToolExecutor(backend, capabilities),
                    session_store=store,
                    session_id=session.session_id,
                    turn_id=turn.turn_id,
                    owner_id="principal_a",
                )
                results = broker.execute_tools_batch([
                    {"id": "call_1", "function": {"name": "write_tool", "arguments": {"value": "one"}}},
                    {"id": "call_2", "function": {"name": "write_tool", "arguments": {"value": "two"}}},
                ])
                self.assertEqual(len(results), 1)
                self.assertEqual(results[0]["result"]["status"], "confirmation_required")
                self.assertEqual(backend.calls, 0)
            finally:
                store.close()

    def test_approved_action_is_exactly_once_and_turn_can_resume(self):
        with tempfile.TemporaryDirectory() as directory:
            store = AgentSessionStore(Path(directory) / "sessions.sqlite3")
            try:
                session = store.create_session("agent", principal_id="principal_a")
                turn = store.start_turn(session.session_id, "write")
                approval = store.create_approval(
                    session.session_id,
                    turn_id=turn.turn_id,
                    tool_id="write_tool",
                    call_id="call_1",
                    arguments_digest="a" * 64,
                    principal_id="principal_a",
                )
                store.transition_turn(turn.turn_id, TurnStatus.RUNNING)
                store.transition_turn(turn.turn_id, TurnStatus.WAITING_FOR_APPROVAL)
                store.resolve_approval(approval.approval_id, principal_id="principal_a", decision=ApprovalStatus.APPROVED)
                resumed = store.resume_approved_turn(approval.approval_id)
                self.assertEqual(resumed.status, TurnStatus.RESUMING)
                consumed = store.consume_approval(
                    approval.approval_id,
                    session_id=session.session_id,
                    turn_id=turn.turn_id,
                    tool_id="write_tool",
                    arguments_digest="a" * 64,
                )
                self.assertEqual(consumed.status, ApprovalStatus.CONSUMED)
                with self.assertRaises(SessionStateConflict):
                    store.consume_approval(
                        approval.approval_id,
                        session_id=session.session_id,
                        turn_id=turn.turn_id,
                        tool_id="write_tool",
                        arguments_digest="a" * 64,
                    )
            finally:
                store.close()

    def test_harness_keeps_turn_waiting_when_agent_requests_approval(self):
        class WaitingLoop:
            def run(self, messages, model, llm_caller, **kwargs):
                raise AgentApprovalRequired(
                    AgentExecutionResult(final_content="", messages=messages, model=model),
                    ["approval_1"],
                )

        with tempfile.TemporaryDirectory() as directory:
            store = AgentSessionStore(Path(directory) / "sessions.sqlite3")
            try:
                session = store.create_session("agent", principal_id="principal_a")
                turn = store.start_turn(session.session_id, "write")
                result = MeshAgentHarness(store, agent_loop=WaitingLoop()).run_turn(
                    session.session_id,
                    turn.turn_id,
                    model="demo-model",
                    llm_caller=lambda messages, tools: {"choices": []},
                )
                self.assertEqual(result.turn.status, TurnStatus.WAITING_FOR_APPROVAL)
                self.assertEqual(result.session.status, SessionStatus.WAITING_FOR_APPROVAL)
                self.assertIn("turn.waiting_for_approval", [event.event_type for event in store.list_events(session.session_id)])
            finally:
                store.close()

    def test_real_agent_loop_stops_at_confirmation_required(self):
        with tempfile.TemporaryDirectory() as directory:
            store = AgentSessionStore(Path(directory) / "sessions.sqlite3")
            try:
                session = store.create_session("agent", principal_id="principal_a")
                turn = store.start_turn(session.session_id, "write")
                backend = _WriteTool()
                capabilities = ToolCapabilityRegistry()
                capabilities.register(ToolManifest(
                    "test_write",
                    "test_write",
                    side_effect=SideEffectLevel.WRITE_REVERSIBLE,
                    confirmation_required=True,
                ))
                broker = AgentToolBroker(
                    SafeToolExecutor(backend, capabilities),
                    session_store=store,
                    session_id=session.session_id,
                    turn_id=turn.turn_id,
                    owner_id="principal_a",
                )
                registry = ToolRegistry(MCPConfig(max_agent_iterations=2))
                registry.register_tool("test_write", "test write", {"type": "object"}, lambda **_: {"ok": True})
                loop = AgentLoop(registry=registry, config=MCPConfig(max_agent_iterations=2))
                result = MeshAgentHarness(store, agent_loop=loop, tool_broker=broker).run_turn(
                    session.session_id,
                    turn.turn_id,
                    model="demo-model",
                    llm_caller=lambda messages, tools: {
                        "choices": [{"message": {"tool_calls": [{
                            "id": "call_write",
                            "type": "function",
                            "function": {"name": "test_write", "arguments": "{\"value\":\"x\"}"},
                        }]}}]
                    },
                )
                self.assertEqual(result.turn.status, TurnStatus.WAITING_FOR_APPROVAL)
                self.assertEqual(backend.calls, 0)
            finally:
                store.close()


if __name__ == "__main__":
    unittest.main()
