# SPDX-License-Identifier: Apache-2.0
"""Regression tests for agent-loop tool execution controls."""

from __future__ import annotations

import json
import unittest

from services.mcp.agent_loop import AgentLoop, MAX_TOOL_CALLS_PER_ITERATION
from services.mcp.config import MCPConfig
from services.mcp.tool_registry import ToolRegistry


class TestAgentLoopHardening(unittest.TestCase):
    def setUp(self):
        self.calls = []
        self.registry = ToolRegistry(MCPConfig(system_tools_enabled=False))
        self.registry.register_tool(
            name="demo_tool",
            description="demo",
            parameters={"type": "object", "properties": {"value": {"type": "integer"}}},
            handler=lambda value=0: self.calls.append(value) or {"value": value},
        )
        self.loop = AgentLoop(registry=self.registry, config=MCPConfig(max_agent_iterations=5))

    def test_malformed_arguments_are_not_executed(self):
        turn = 0

        def llm(_messages, _tools):
            nonlocal turn
            turn += 1
            if turn == 1:
                return {"choices": [{"message": {"tool_calls": [{
                    "id": "x",
                    "type": "function",
                    "function": {"name": "demo_tool", "arguments": "{broken"},
                }]}}]}
            return {"choices": [{"message": {"content": "fertig"}}]}

        result = self.loop.run([{"role": "user", "content": "x"}], "demo", llm)
        self.assertEqual(self.calls, [])
        self.assertIn("kein gültiges JSON", result.tool_calls_executed[0].result["error"])

    def test_disabled_canonical_tool_cannot_be_called_via_alias(self):
        turn = 0

        def llm(_messages, _tools):
            nonlocal turn
            turn += 1
            if turn == 1:
                return {"choices": [{"message": {
                    "content": json.dumps({"name": "weather", "arguments": {"location": "Berlin"}})
                }}]}
            return {"choices": [{"message": {"content": "blocked"}}]}

        result = self.loop.run(
            [{"role": "user", "content": "weather"}],
            "demo",
            llm,
            disabled_tools=["get_current_weather"],
        )
        self.assertEqual(result.tool_calls_executed[0].name, "weather")
        self.assertIn("deaktiviert", result.tool_calls_executed[0].result["error"])

    def test_tool_calls_per_iteration_are_capped(self):
        turn = 0

        def llm(_messages, _tools):
            nonlocal turn
            turn += 1
            if turn == 1:
                calls = [
                    {
                        "id": f"c{i}",
                        "type": "function",
                        "function": {"name": "demo_tool", "arguments": json.dumps({"value": i})},
                    }
                    for i in range(MAX_TOOL_CALLS_PER_ITERATION + 5)
                ]
                return {"choices": [{"message": {"tool_calls": calls}}]}
            return {"choices": [{"message": {"content": "done"}}]}

        result = self.loop.run([{"role": "user", "content": "many"}], "demo", llm)
        self.assertEqual(len(result.tool_calls_executed), MAX_TOOL_CALLS_PER_ITERATION)
        self.assertEqual(len(self.calls), MAX_TOOL_CALLS_PER_ITERATION)

    def test_max_iterations_is_clamped_to_positive_bound(self):
        def llm(_messages, _tools):
            return {"choices": [{"message": {"content": "done"}}]}

        result = self.loop.run([], "demo", llm, max_iterations=999)
        self.assertEqual(result.iterations, 1)


if __name__ == "__main__":
    unittest.main()
