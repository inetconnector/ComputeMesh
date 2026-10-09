"""Tests for redacted durable trace spans."""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from services.mcp.platform.tracing import TraceStore


class TestTraceStore(unittest.TestCase):
    def test_parent_child_and_redaction_survive_restart(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            database = Path(directory) / "traces.sqlite3"
            store = TraceStore(database)
            root = store.start(
                session_id="sess_1",
                turn_id="turn_1",
                kind="turn",
                name="agent.turn",
                attributes={"model": "demo", "api_key": "do-not-store"},
            )
            child = store.start(
                session_id="sess_1",
                turn_id="turn_1",
                kind="tool",
                name="tool.call",
                trace_id=root.trace_id,
                parent_span_id=root.span_id,
            )
            store.finish(child.span_id, status="failed", attributes={"error_type": "TimeoutError"})
            store.finish(root.span_id, status="completed")
            spans = store.list_for_session("sess_1")
            self.assertEqual(len(spans), 2)
            self.assertEqual(spans[1].parent_span_id, root.span_id)
            self.assertEqual(spans[0].attributes["api_key"], "[REDACTED]")
            store.close()
            reopened = TraceStore(database)
            try:
                self.assertEqual(len(reopened.list_for_session("sess_1")), 2)
            finally:
                reopened.close()


if __name__ == "__main__":
    unittest.main()
