"""Tests for durable agent pause/resume/cancel controls."""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from services.mcp.platform.session import (
    AgentSessionStore,
    ControlStatus,
    SessionStateConflict,
    SessionStatus,
    TurnStatus,
)


class TestAgentControls(unittest.TestCase):
    def test_queued_turn_can_be_paused_and_resumed_without_worker_claim(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = AgentSessionStore(Path(directory) / "sessions.sqlite3")
            try:
                session = store.create_session("mesh.agent", principal_id="principal_a")
                turn = store.start_turn(session.session_id, "hello")

                paused = store.request_control(
                    session.session_id,
                    "pause",
                    principal_id="principal_a",
                    turn_id=turn.turn_id,
                )
                self.assertEqual(paused.status, ControlStatus.APPLIED)
                self.assertEqual(store.get_turn(turn.turn_id).status, TurnStatus.PAUSED)
                self.assertEqual(store.get_session(session.session_id).status, SessionStatus.PAUSED)
                self.assertIsNone(store.claim_turn(turn.turn_id, worker_id="worker_a"))

                resumed = store.request_control(
                    session.session_id,
                    "resume",
                    principal_id="principal_a",
                    turn_id=turn.turn_id,
                )
                self.assertEqual(resumed.status, ControlStatus.APPLIED)
                self.assertEqual(store.get_turn(turn.turn_id).status, TurnStatus.RESUMING)
                self.assertEqual(store.get_session(session.session_id).status, SessionStatus.READY)
                self.assertIsNotNone(store.claim_turn(turn.turn_id, worker_id="worker_a"))
                with self.assertRaises(SessionStateConflict):
                    store.start_turn(session.session_id, "must wait for resumed turn")
            finally:
                store.close()

    def test_running_turn_control_waits_for_safe_worker_boundary(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = AgentSessionStore(Path(directory) / "sessions.sqlite3")
            try:
                session = store.create_session("mesh.agent", principal_id="principal_a")
                turn = store.start_turn(session.session_id, "hello")
                self.assertIsNotNone(store.claim_turn(turn.turn_id, worker_id="worker_a"))

                requested = store.request_control(
                    session.session_id,
                    "cancel",
                    principal_id="principal_a",
                    turn_id=turn.turn_id,
                )
                self.assertEqual(requested.status, ControlStatus.REQUESTED)
                self.assertEqual(store.get_turn(turn.turn_id).status, TurnStatus.RUNNING)

                applied = store.apply_pending_control(session.session_id, turn.turn_id, "cancel")
                self.assertEqual(applied.status, ControlStatus.APPLIED)
                self.assertEqual(store.get_turn(turn.turn_id).status, TurnStatus.CANCELLED)
                self.assertEqual(store.get_session(session.session_id).status, SessionStatus.READY)
            finally:
                store.close()

    def test_control_requires_session_owner(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = AgentSessionStore(Path(directory) / "sessions.sqlite3")
            try:
                session = store.create_session("mesh.agent", principal_id="principal_a")
                turn = store.start_turn(session.session_id, "hello")
                with self.assertRaises(PermissionError):
                    store.request_control(
                        session.session_id,
                        "cancel",
                        principal_id="principal_b",
                        turn_id=turn.turn_id,
                    )
            finally:
                store.close()


if __name__ == "__main__":
    unittest.main()
