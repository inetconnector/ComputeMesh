# SPDX-License-Identifier: Apache-2.0
"""Regression coverage for current TV-programme questions."""

from __future__ import annotations

import unittest
from unittest.mock import patch

from services.mcp.agent_loop import AgentLoop
from services.mcp.intent.intent_router import detect_direct_tool_intent
from services.mcp.tool_registry import ToolRegistry


class TvProgramRoutingTests(unittest.TestCase):
    def test_german_zdf_schedule_question_requires_live_web_search(self) -> None:
        intent = detect_direct_tool_intent("was kommt denn heute auf ZDF im Fernseher")

        self.assertIsNotNone(intent)
        self.assertEqual(intent[0], "search_web")
        self.assertIn("ZDF", intent[1]["query"])
        self.assertIn("heute", intent[1]["query"])
        self.assertEqual(intent[1]["max_results"], 8)

    def test_schedule_without_channel_still_uses_live_search(self) -> None:
        intent = detect_direct_tool_intent("Was läuft heute im TV?")

        self.assertIsNotNone(intent)
        self.assertEqual(intent[0], "search_web")

    def test_generic_television_question_defaults_to_current_schedule(self) -> None:
        intent = detect_direct_tool_intent("Was kommt im Fernseher?")

        self.assertIsNotNone(intent)
        self.assertEqual(intent[0], "search_web")
        self.assertIn("jetzt", intent[1]["query"])

    def test_agent_loop_executes_live_search_before_answering(self) -> None:
        registry = ToolRegistry()
        loop = AgentLoop(registry)
        live_result = {
            "query": "TV-Programm zdf heute",
            "source": "test-live-source",
            "results": [{"title": "Heute 20:15", "url": "https://zdf.de", "snippet": "Live result"}],
        }

        calls_seen: list[list[dict[str, object]]] = []

        def llm_caller(messages, tools):
            calls_seen.append(tools)
            return {
                "choices": [{"message": {"role": "assistant", "content": "Auf Basis der Live-Daten: Heute 20:15."}}]
            }

        with patch.object(registry, "execute_tool", return_value=live_result) as execute_tool:
            result = loop.run(
                messages=[{"role": "user", "content": "was kommt denn heute auf ZDF im Fernseher"}],
                model="qwen2.5:7b",
                llm_caller=llm_caller,
            )

        execute_tool.assert_called_once()
        self.assertEqual(calls_seen, [[]])
        self.assertEqual(execute_tool.call_args.args[0], "search_web")
        self.assertEqual(result.tool_calls_executed[0].name, "search_web")
        self.assertIn("Live-Daten", result.final_content)


if __name__ == "__main__":
    unittest.main()
