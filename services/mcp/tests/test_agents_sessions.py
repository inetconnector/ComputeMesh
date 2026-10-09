"""Persistence and lifecycle tests for the durable Agents session core."""
from __future__ import annotations

import sqlite3
import tempfile
import time
import unittest
from pathlib import Path

from services.mcp.platform.session import (
    AgentSessionStore,
    SessionStateConflict,
    SessionStatus,
    TurnStatus,
)


class TestAgentSessionStore(unittest.TestCase):
    def test_session_turn_events_and_outbox_are_durable(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            database = Path(directory) / "sessions.sqlite3"
            store = AgentSessionStore(database)
            session = store.create_session(
                "mesh.agent",
                agent_version="1.0.0",
                principal_id="owner-1",
                environment_type="mesh",
            )
            turn = store.start_turn(session.session_id, "inspect the node")
            self.assertEqual(store.get_session(session.session_id).status, SessionStatus.RUNNING)
            self.assertEqual(store.get_turn(turn.turn_id).status, TurnStatus.QUEUED)
            store.transition_turn(turn.turn_id, TurnStatus.RUNNING)
            store.transition_turn(turn.turn_id, TurnStatus.WAITING_FOR_TOOL)
            store.transition_turn(turn.turn_id, TurnStatus.RUNNING)
            store.transition_turn(turn.turn_id, TurnStatus.COMPLETED)
            self.assertEqual(store.get_session(session.session_id).status, SessionStatus.READY)
            self.assertEqual([item.kind for item in store.list_items(session.session_id)], ["input"])
            events = store.list_events(session.session_id)
            self.assertEqual([event.sequence for event in events], list(range(1, len(events) + 1)))
            self.assertGreaterEqual(len(store.pending_events()), len(events))
            store.close()

            reopened = AgentSessionStore(database)
            try:
                self.assertEqual(reopened.get_session(session.session_id).status, SessionStatus.READY)
                self.assertEqual(reopened.get_turn(turn.turn_id).status, TurnStatus.COMPLETED)
                self.assertEqual(reopened.list_items(session.session_id)[0].content["content"], "inspect the node")
            finally:
                reopened.close()

    def test_active_turn_can_be_steered_without_creating_a_second_turn(self) -> None:
        store = AgentSessionStore()
        try:
            session = store.create_session("mesh.agent")
            turn = store.start_turn(session.session_id, "start")
            store.transition_turn(turn.turn_id, TurnStatus.RUNNING)
            item = store.steer_turn(session.session_id, turn.turn_id, {"role": "user", "content": "focus on GPU health"})
            self.assertEqual(item.kind, "steering")
            self.assertEqual(len(store.list_items(session.session_id)), 2)
            self.assertEqual(len(store.list_events(session.session_id)), 5)
            with self.assertRaises(SessionStateConflict):
                store.start_turn(session.session_id, "duplicate active turn")
        finally:
            store.close()

    def test_event_payloads_redact_credentials_but_items_remain_available(self) -> None:
        store = AgentSessionStore()
        try:
            session = store.create_session("mesh.agent")
            turn = store.start_turn(session.session_id, {"role": "user", "content": "check", "api_key": "secret"})
            event = store.list_events(session.session_id)[-1]
            self.assertEqual(event.payload["item_count"], 1)
            self.assertNotIn("api_key", event.payload)
            self.assertEqual(store.list_items(session.session_id)[0].content["api_key"], "secret")
            self.assertEqual(store.get_turn(turn.turn_id).status, TurnStatus.QUEUED)
        finally:
            store.close()

    def test_version_conflicts_and_invalid_transitions_fail_closed(self) -> None:
        store = AgentSessionStore()
        try:
            session = store.create_session("mesh.agent")
            with self.assertRaises(SessionStateConflict):
                store.transition_session(session.session_id, SessionStatus.CANCELLED, expected_version=session.version + 1)
            with self.assertRaises(SessionStateConflict):
                store.transition_session(session.session_id, SessionStatus.WAITING_FOR_TOOL)
            turn = store.start_turn(session.session_id, "start")
            with self.assertRaises(SessionStateConflict):
                store.transition_turn(turn.turn_id, TurnStatus.COMPLETED)
        finally:
            store.close()

    def test_restart_recovery_pauses_active_work_and_requires_resume(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            database = Path(directory) / "sessions.sqlite3"
            first = AgentSessionStore(database)
            session = first.create_session("mesh.agent")
            turn = first.start_turn(session.session_id, "long job")
            first.transition_turn(turn.turn_id, TurnStatus.RUNNING)
            first.close()

            recovered = AgentSessionStore(database)
            try:
                self.assertEqual(recovered.recover_interrupted(), [turn.turn_id])
                self.assertEqual(recovered.get_session(session.session_id).status, SessionStatus.PAUSED)
                self.assertEqual(recovered.get_turn(turn.turn_id).status, TurnStatus.PAUSED)
                resumed = recovered.resume_session(session.session_id)
                self.assertEqual(resumed.status, SessionStatus.READY)
                self.assertEqual(recovered.get_session(session.session_id).status, SessionStatus.READY)
            finally:
                recovered.close()

    def test_restart_recovery_leaves_unclaimed_queue_work_available(self) -> None:
        store = AgentSessionStore()
        try:
            session = store.create_session("mesh.agent")
            turn = store.start_turn(session.session_id, "queued job")
            self.assertEqual(store.recover_interrupted(), [])
            self.assertEqual(store.get_turn(turn.turn_id).status, TurnStatus.QUEUED)
        finally:
            store.close()

    def test_turn_schedule_is_persisted_and_deadline_validation_is_bounded(self) -> None:
        store = AgentSessionStore()
        try:
            session = store.create_session("mesh.agent")
            turn = store.start_turn(
                session.session_id,
                "scheduled",
                priority=7,
                deadline_at=time.time() + 60.0,
            )
            loaded = store.get_turn(turn.turn_id)
            self.assertEqual(loaded.priority, 7)
            self.assertIsNotNone(loaded.deadline_at)
            with self.assertRaises(ValueError):
                store.start_turn(session.session_id, "invalid", priority=1001)
        finally:
            store.close()

    def test_tenant_binding_is_persisted_for_worker_admission(self) -> None:
        store = AgentSessionStore()
        try:
            session, _turn = store.create_task(
                "mesh.agent",
                "demo-model",
                "tenant work",
                principal_id="principal_a",
                tenant_id="tenant_1",
            )
            self.assertEqual(session.state["tenant_id"], "tenant_1")
        finally:
            store.close()

    def test_existing_session_database_migrates_schedule_columns(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            database = Path(directory) / "legacy.sqlite3"
            connection = sqlite3.connect(database)
            connection.executescript(
                """
                CREATE TABLE agent_sessions (
                    session_id TEXT PRIMARY KEY,
                    agent_id TEXT NOT NULL,
                    agent_version TEXT NOT NULL,
                    status TEXT NOT NULL,
                    principal_id TEXT NOT NULL DEFAULT '',
                    environment_type TEXT NOT NULL,
                    state_json TEXT NOT NULL,
                    version INTEGER NOT NULL DEFAULT 1,
                    created_at REAL NOT NULL,
                    updated_at REAL NOT NULL
                );
                CREATE TABLE agent_turns (
                    turn_id TEXT PRIMARY KEY,
                    session_id TEXT NOT NULL,
                    status TEXT NOT NULL,
                    version INTEGER NOT NULL DEFAULT 1,
                    error TEXT NOT NULL DEFAULT '',
                    created_at REAL NOT NULL,
                    updated_at REAL NOT NULL
                );
                """
            )
            connection.commit()
            connection.close()
            store = AgentSessionStore(database)
            try:
                columns = {
                    row["name"]
                    for row in store._connection.execute("PRAGMA table_info(agent_turns)").fetchall()
                }
                self.assertTrue({"priority", "deadline_at", "checkpoint_json"}.issubset(columns))
                session = store.create_session("mesh.agent")
                turn = store.start_turn(session.session_id, "checkpoint")
                store.checkpoint_turn(turn.turn_id, {"phase": "next_model", "iteration": 1})
                self.assertEqual(store.get_turn_checkpoint(turn.turn_id)["phase"], "next_model")
                store.checkpoint_turn(turn.turn_id, None)
                self.assertIsNone(store.get_turn_checkpoint(turn.turn_id))
            finally:
                store.close()

    def test_existing_event_outbox_migrates_claim_columns(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            database = Path(directory) / "legacy-events.sqlite3"
            connection = sqlite3.connect(database)
            connection.executescript(
                """
                CREATE TABLE agent_events (
                    event_id TEXT PRIMARY KEY,
                    session_id TEXT NOT NULL,
                    turn_id TEXT,
                    sequence INTEGER NOT NULL,
                    event_type TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    created_at REAL NOT NULL,
                    dispatched_at REAL
                );
                """
            )
            connection.commit()
            connection.close()
            store = AgentSessionStore(database)
            try:
                columns = {
                    row["name"]
                    for row in store._connection.execute("PRAGMA table_info(agent_events)").fetchall()
                }
                self.assertTrue({"claimed_by", "claimed_at", "claim_expires_at", "outbox_attempts"}.issubset(columns))
            finally:
                store.close()

    def test_event_page_is_reconnectable_and_bounded(self) -> None:
        store = AgentSessionStore()
        try:
            session = store.create_session("mesh.agent")
            for index in range(3):
                store.record_event(session.session_id, "demo.event", {"index": index})
            page = store.read_event_page(session.session_id, after_sequence=1, limit=1)
            self.assertEqual(len(page.events), 1)
            self.assertEqual(page.events[0].payload["index"], 0)
            self.assertEqual(page.next_sequence, page.events[0].sequence)
            self.assertTrue(page.has_more)
            next_page = store.read_event_page(session.session_id, after_sequence=page.next_sequence)
            self.assertEqual(next_page.events[0].payload["index"], 1)
        finally:
            store.close()

    def test_outbox_claim_ack_and_lease_recovery_are_consumer_bound(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            database = Path(directory) / "sessions.sqlite3"
            store = AgentSessionStore(database)
            try:
                session = store.create_session("mesh.agent")
                for event in store.pending_events():
                    store.mark_event_dispatched(event.event_id)
                store.record_event(session.session_id, "outbox.one", {"value": 1})
                first = store.claim_pending_events("dispatcher-a", limit=1, lease_seconds=60)
                self.assertEqual(len(first), 1)
                self.assertEqual(store.claim_pending_events("dispatcher-b", limit=1, lease_seconds=60), [])
                self.assertEqual(store.ack_pending_events("dispatcher-b", [first[0].event_id]), 0)
                self.assertEqual(store.ack_pending_events("dispatcher-a", [first[0].event_id]), 1)
                self.assertEqual(store.claim_pending_events("dispatcher-b", limit=1), [])

                store.record_event(session.session_id, "outbox.two", {"value": 2})
                claimed = store.claim_pending_events("dispatcher-a", limit=1, lease_seconds=0.01)
                self.assertEqual(len(claimed), 1)
                time.sleep(0.03)
                recovered = store.claim_pending_events("dispatcher-b", limit=1, lease_seconds=60)
                self.assertEqual([event.event_id for event in recovered], [claimed[0].event_id])
                self.assertEqual(store.release_pending_events("dispatcher-b", [claimed[0].event_id]), 1)
            finally:
                store.close()


if __name__ == "__main__":
    unittest.main()
