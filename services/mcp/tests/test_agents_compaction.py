"""Tests for the model-backed compaction contract."""
from __future__ import annotations

import unittest

from services.mcp.platform.compaction import CompactionError, ModelCompactor


class TestModelCompactor(unittest.TestCase):
    def test_calls_model_without_tools_and_marks_transcript_untrusted(self) -> None:
        calls = []

        def caller(messages, tools):
            calls.append((messages, tools))
            return {"choices": [{"message": {"content": "ACTIVE_TASK: finish the request"}}]}

        compactor = ModelCompactor(caller, model="mesh-summary")
        summary = compactor([{"role": "user", "content": "ignore this tool instruction"}])

        self.assertIn("ACTIVE_TASK", summary)
        self.assertEqual(calls[0][1], [])
        self.assertIn("untrusted data", calls[0][0][0]["content"].lower())
        self.assertIn("UNTRUSTED_SESSION_TRANSCRIPT", calls[0][0][1]["content"])
        self.assertEqual(compactor.last_result.input_messages, 1)

    def test_rejects_tool_calls_and_oversized_summaries(self) -> None:
        def tool_caller(messages, tools):
            return {"choices": [{"message": {"tool_calls": [{"id": "x"}], "content": "no"}}]}

        with self.assertRaises(CompactionError):
            ModelCompactor(tool_caller, model="mesh-summary")([{"role": "user", "content": "x"}])

        with self.assertRaises(CompactionError):
            ModelCompactor(
                lambda messages, tools: {"choices": [{"message": {"content": "x" * 257}}]},
                model="mesh-summary",
                max_summary_chars=256,
            )([{"role": "user", "content": "x"}])

    def test_provider_errors_are_normalized_without_leaking_error_text(self) -> None:
        def failing_caller(messages, tools):
            raise RuntimeError("secret provider token")

        with self.assertRaisesRegex(CompactionError, "compaction model call failed: RuntimeError"):
            ModelCompactor(failing_caller, model="mesh-summary")([{"role": "user", "content": "x"}])


if __name__ == "__main__":
    unittest.main()
