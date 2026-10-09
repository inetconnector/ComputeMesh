"""Tests for the authenticated, bounded agent-session projection."""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from services.mcp.platform.session import AgentSessionStore
from services.mcp.platform.session_projection import (
    SessionProjectionDenied,
    project_events,
    project_session,
    project_sessions,
)


class TestAgentSessionProjection(unittest.TestCase):
    def test_projection_omits_private_state_and_supports_cursor(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = AgentSessionStore(Path(directory) / "sessions.sqlite3")
            session = store.create_session(
                "research",
                agent_version="2",
                principal_id="acct-a",
                state={"secret": "must-not-leak", "internal": "private"},
                session_id="sess_projection",
            )
            store.record_event(session.session_id, "progress", {"step": 1, "token": "hidden"})
            store.record_event(session.session_id, "progress", {"step": 2})

            summary = project_session(store, session.session_id, principal_id="acct-a")
            self.assertNotIn("state", summary["session"])
            self.assertNotIn("principal_id", summary["session"])
            listed = project_sessions(store, principal_id="acct-a")
            self.assertEqual([item["session_id"] for item in listed["sessions"]], ["sess_projection"])

            first = project_events(store, session.session_id, principal_id="acct-a", limit=1)
            self.assertEqual(len(first["events"]), 1)
            self.assertEqual(first["next_sequence"], 1)
            self.assertNotIn("token", first["events"][0]["payload"])
            second = project_events(
                store,
                session.session_id,
                principal_id="acct-a",
                after_sequence=first["next_sequence"],
            )
            self.assertEqual([event["payload"].get("step") for event in second["events"]], [1, 2])
            store.close()

    def test_projection_rejects_other_principal(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = AgentSessionStore(Path(directory) / "sessions.sqlite3")
            store.create_session("research", principal_id="acct-a", session_id="sess_owner")
            with self.assertRaises(SessionProjectionDenied):
                project_events(store, "sess_owner", principal_id="acct-b")
            store.close()


if __name__ == "__main__":
    unittest.main()
