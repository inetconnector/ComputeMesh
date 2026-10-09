"""Regression tests for the durable, policy-backed tool broker."""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from services.mcp.platform.contracts import SideEffectLevel, ToolManifest
from services.mcp.platform.session import AgentSessionStore
from services.mcp.platform.tool_broker import AgentToolBroker
from services.mcp.platform.tool_execution import SafeToolExecutor, ToolCapabilityRegistry


class _Tool:
    def __init__(self, name: str) -> None:
        self.name = name
        self.description = name
        self.parameters = {"type": "object", "properties": {}}


class _Backend:
    def __init__(self) -> None:
        self.calls = 0
        self.tools = {"read_tool": _Tool("read_tool")}

    def get_tool(self, name: str):
        return self.tools.get(name)

    def list_tools(self, is_owner: bool = True):
        return list(self.tools.values())

    def execute_tool(self, name, arguments, is_owner=True, owner_id=None):
        self.calls += 1
        return {"value": "private-result", **arguments}


class TestAgentToolBroker(unittest.TestCase):
    def test_events_contain_metadata_but_not_tool_result(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = AgentSessionStore(Path(directory) / "sessions.sqlite3")
            try:
                session = store.create_session("mesh.agent")
                turn = store.start_turn(session.session_id, "run")
                backend = _Backend()
                capabilities = ToolCapabilityRegistry()
                capabilities.register(ToolManifest("read_tool", "read_tool", side_effect=SideEffectLevel.READ, confirmation_required=False, idempotent=True))
                executor = SafeToolExecutor(backend, capabilities)
                broker = AgentToolBroker(
                    executor,
                    session_store=store,
                    session_id=session.session_id,
                    turn_id=turn.turn_id,
                )

                result = broker.execute_tool("read_tool", {"x": 1}, call_id="call_1")

                self.assertEqual(result["value"], "private-result")
                self.assertEqual(backend.calls, 1)
                events = store.list_events(session.session_id)
                names = [event.event_type for event in events]
                self.assertEqual(names[-3:], ["tool.requested", "tool.started", "tool.completed"])
                self.assertTrue(all("private-result" not in str(event.payload) for event in events))
                self.assertTrue(events[-1].payload["result_digest"])
            finally:
                store.close()

    def test_batch_keeps_call_ids_and_invalid_arguments_are_not_executed(self) -> None:
        backend = _Backend()
        capabilities = ToolCapabilityRegistry()
        capabilities.register(ToolManifest("read_tool", "read_tool", side_effect=SideEffectLevel.READ, confirmation_required=False, idempotent=True))
        broker = AgentToolBroker(SafeToolExecutor(backend, capabilities))

        results = broker.execute_tools_batch([
            {"id": "good", "function": {"name": "read_tool", "arguments": '{"x": 2}'}},
            {"id": "bad", "function": {"name": "read_tool", "arguments": "not-json"}},
        ])

        self.assertEqual([item["id"] for item in results], ["good", "bad"])
        self.assertEqual(backend.calls, 1)
        self.assertIn("invalid JSON arguments", results[1]["result"]["error"])


if __name__ == "__main__":
    unittest.main()
