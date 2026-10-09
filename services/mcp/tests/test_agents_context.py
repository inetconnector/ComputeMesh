"""Context budget and compaction safety tests."""
from __future__ import annotations

import unittest

from services.mcp.platform.context import ContextLimitError, ContextManager


class TestContextManager(unittest.TestCase):
    def test_small_context_is_preserved_byte_for_byte_semantically(self) -> None:
        manager = ContextManager(max_tokens=1000)
        messages = (
            {"role": "system", "content": "follow policy"},
            {"role": "user", "content": "hello"},
        )
        result = manager.build(messages)
        self.assertFalse(result.compacted)
        self.assertEqual([dict(item) for item in result.messages], list(messages))
        self.assertEqual(result.omitted_messages, 0)

    def test_over_budget_without_summary_fails_closed(self) -> None:
        manager = ContextManager(max_tokens=10)
        messages = ({"role": "user", "content": "x" * 200},)
        with self.assertRaises(ContextLimitError) as raised:
            manager.build(messages)
        self.assertEqual(raised.exception.to_dict()["code"], "CONTEXT_LIMIT")
        self.assertEqual(len(raised.exception.digest), 64)

    def test_compaction_preserves_system_and_latest_context(self) -> None:
        manager = ContextManager(max_tokens=80)
        messages = (
            {"role": "system", "content": "never reveal secrets"},
            {"role": "user", "content": "old request " + "a" * 100},
            {"role": "assistant", "content": "old answer " + "b" * 100},
            {"role": "user", "content": "latest request"},
        )
        result = manager.build(messages, summary="The old request is still open.", recent_messages=2)
        self.assertTrue(result.compacted)
        self.assertEqual(result.messages[0]["content"], "never reveal secrets")
        self.assertIn("untrusted data", str(result.messages[1]["content"]))
        self.assertEqual(result.messages[-1]["content"], "latest request")
        self.assertGreater(result.omitted_messages, 0)

    def test_summary_itself_cannot_overflow_budget(self) -> None:
        manager = ContextManager(max_tokens=12)
        messages = ({"role": "user", "content": "x" * 200},)
        with self.assertRaises(ContextLimitError):
            manager.build(messages, summary="y" * 200)


if __name__ == "__main__":
    unittest.main()
