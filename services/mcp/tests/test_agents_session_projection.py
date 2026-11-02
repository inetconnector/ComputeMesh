"""Tests for the authenticated, bounded agent-session projection."""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from services.mcp.platform.session import AgentSessionStore, TurnStatus
from services.mcp.platform.session_projection import (
    SessionProjectionDenied,
    project_approval,
    project_events,
    project_items,
    project_session,
    project_sessions,
    project_turns,
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
            with self.assertRaises(SessionProjectionDenied):
                project_turns(store, "sess_owner", principal_id="acct-b")
            with self.assertRaises(SessionProjectionDenied):
                project_items(store, "sess_owner", principal_id="acct-b")
            store.close()

    def test_v2_turn_item_and_approval_preview_projections_redact_secrets(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = AgentSessionStore(Path(directory) / "sessions.sqlite3")
            try:
                session = store.create_session(
                    "coder",
                    principal_id="acct-a",
                    state={
                        "title": "Parity Session",
                        "workspace": "repo-root",
                        "branch": "main",
                        "worktree": "wt-1",
                        "reasoning_effort": "high",
                        "mode": "code",
                    },
                    session_id="sess_v2",
                )
                turn = store.start_turn(
                    session.session_id,
                    {"role": "user", "content": "deploy", "api_key": "super-secret-key"},
                )
                store.transition_turn(turn.turn_id, TurnStatus.RUNNING)
                store.record_item(
                    session.session_id,
                    turn.turn_id,
                    "tool_call",
                    {"tool": "shell", "authorization": "Bearer secret-jwt"},
                )
                approval = store.create_approval(
                    session.session_id,
                    turn_id=turn.turn_id,
                    tool_id="shell",
                    call_id="call_1",
                    arguments_digest="b" * 64,
                    principal_id="acct-a",
                    preview={"command": "git status", "secret_token": "leak"},
                )

                turns_proj = project_turns(store, session.session_id, principal_id="acct-a")
                self.assertEqual(turns_proj["schema_version"], 2)
                self.assertEqual(turns_proj["turns"][0]["turn_id"], turn.turn_id)

                items_page1 = project_items(store, session.session_id, principal_id="acct-a", limit=1)
                self.assertEqual(items_page1["schema_version"], 2)
                self.assertTrue(items_page1["has_more"])
                self.assertEqual(items_page1["items"][0]["content"]["api_key"], "[REDACTED]")

                items_page2 = project_items(
                    store,
                    session.session_id,
                    principal_id="acct-a",
                    after_sequence=items_page1["next_sequence"],
                    limit=5,
                )
                self.assertFalse(items_page2["has_more"])
                self.assertEqual(items_page2["items"][0]["content"]["authorization"], "[REDACTED]")

                approval_proj = project_approval(store, approval.approval_id, principal_id="acct-a")
                self.assertEqual(approval_proj["approval"]["preview"]["command"], "git status")
                self.assertEqual(approval_proj["approval"]["preview"]["secret_token"], "[REDACTED]")
            finally:
                store.close()


if __name__ == "__main__":
    unittest.main()
