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

    def test_cursor_pagination_search_filter_pin_archive_restore(self) -> None:
        store = AgentSessionStore()
        try:
            s1 = store.create_session(
                "mesh.agent",
                principal_id="principal_a",
                state={"title": "Alpha Router Audit", "workspace": "ws-core"},
                session_id="sess_a1",
            )
            time.sleep(0.002)
            s2 = store.create_session(
                "mesh.agent",
                principal_id="principal_a",
                state={"title": "Beta Gateway Refactor", "workspace": "ws-gateway"},
                session_id="sess_a2",
            )
            time.sleep(0.002)
            s3 = store.create_session(
                "mesh.agent",
                principal_id="principal_a",
                state={"title": "Gamma Security Gate", "workspace": "ws-core"},
                session_id="sess_a3",
            )
            store.create_session(
                "mesh.agent",
                principal_id="principal_b",
                state={"title": "Alpha Foreign Secret", "workspace": "ws-core"},
                session_id="sess_b1",
            )

            # Pin s1, archive and then restore s2
            pinned = store.update_metadata(s1.session_id, {"pinned": True}, expected_version=s1.version)
            self.assertTrue(pinned.state["pinned"])
            with self.assertRaises(SessionStateConflict):
                store.update_metadata(s1.session_id, {"title": "stale"}, expected_version=s1.version)

            archived = store.update_metadata(s2.session_id, {"archived": True}, expected_version=s2.version)
            self.assertTrue(archived.state["archived"])
            restored = store.update_metadata(s2.session_id, {"archived": False}, expected_version=archived.version)
            self.assertFalse(restored.state["archived"])
            event_types = [ev.event_type for ev in store.list_events(s2.session_id)]
            self.assertIn("session.restored", event_types)

            # Filter by principal_a + search + workspace + pinned
            search_hits = store.list_sessions(principal_id="principal_a", search="alpha")
            self.assertEqual([item.session_id for item in search_hits], ["sess_a1"])
            ws_hits = store.list_sessions(principal_id="principal_a", workspace="ws-core")
            self.assertEqual({item.session_id for item in ws_hits}, {"sess_a1", "sess_a3"})
            pinned_hits = store.list_sessions(principal_id="principal_a", pinned=True)
            self.assertEqual([item.session_id for item in pinned_hits], ["sess_a1"])

            # Cursor pagination over principal_a's 3 sessions (limit=2)
            page1, cursor1, has_more1 = store.list_sessions_page(principal_id="principal_a", limit=2)
            self.assertEqual(len(page1), 2)
            self.assertTrue(has_more1)
            self.assertIsNotNone(cursor1)
            page2, cursor2, has_more2 = store.list_sessions_page(
                principal_id="principal_a",
                limit=2,
                cursor=cursor1,
            )
            self.assertEqual(len(page2), 1)
            self.assertFalse(has_more2)
            self.assertIsNone(cursor2)
            self.assertEqual(
                {s.session_id for s in page1} | {s.session_id for s in page2},
                {s1.session_id, s2.session_id, s3.session_id},
            )
        finally:
            store.close()

    def test_fork_and_side_chat_preserve_isolation_and_owner_boundaries(self) -> None:
        store = AgentSessionStore()
        try:
            parent = store.create_session(
                "mesh.agent",
                principal_id="principal_a",
                state={"title": "Main Thread", "model": "qwen2.5:7b", "workspace": "ws-1", "branch": "main"},
                session_id="sess_parent",
            )
            turn = store.start_turn(parent.session_id, "step one")
            store.transition_turn(turn.turn_id, TurnStatus.RUNNING)
            store.record_item(parent.session_id, turn.turn_id, "output", {"role": "assistant", "content": "step one reply"})
            store.record_item(parent.session_id, turn.turn_id, "output", {"role": "assistant", "content": "step two reply"})

            # Cross-principal fork/side-chat must fail closed
            with self.assertRaises(PermissionError):
                store.fork_session(parent.session_id, principal_id="principal_b")
            with self.assertRaises(PermissionError):
                store.create_side_chat(parent.session_id, principal_id="principal_b")

            # Fork up to sequence 2 (omits sequence 3)
            forked = store.fork_session(
                parent.session_id,
                principal_id="principal_a",
                up_to_sequence=2,
                title="Forked Thread",
                session_id="sess_fork",
            )
            self.assertEqual(forked.state["parent_session_id"], parent.session_id)
            self.assertEqual(forked.state["session_kind"], "fork")
            self.assertEqual(forked.state["fork_from_sequence"], 2)
            fork_items = store.list_items(forked.session_id)
            self.assertEqual(len(fork_items), 2)
            self.assertEqual(len(store.list_items(parent.session_id)), 3)

            # Side-chat while parent turn is still running
            side_chat = store.create_side_chat(
                parent.session_id,
                principal_id="principal_a",
                context_turn_id=turn.turn_id,
                title="Quick Question",
                session_id="sess_side",
            )
            self.assertEqual(side_chat.state["parent_session_id"], parent.session_id)
            self.assertEqual(side_chat.state["session_kind"], "side_chat")
            self.assertEqual(side_chat.state["context_turn_id"], turn.turn_id)
            side_turn = store.start_turn(side_chat.session_id, "explain the error")
            self.assertEqual(side_turn.status, TurnStatus.QUEUED)
            self.assertEqual(store.get_turn(turn.turn_id).status, TurnStatus.RUNNING)
        finally:
            store.close()

    def test_queue_steer_expected_version_cas_and_idempotency_replay(self) -> None:
        store = AgentSessionStore()
        try:
            session = store.create_session("mesh.agent", principal_id="principal_a")
            t1 = store.start_turn(
                session.session_id,
                "first task",
                expected_version=session.version,
                idempotency_key="turn-key-1",
            )
            # Replay with same idempotency_key returns identical turn without conflict
            t1_replay = store.start_turn(
                session.session_id,
                "first task",
                expected_version=999,
                idempotency_key="turn-key-1",
            )
            self.assertEqual(t1.turn_id, t1_replay.turn_id)

            store.transition_turn(t1.turn_id, TurnStatus.RUNNING)
            running_session = store.get_session(session.session_id)

            # Queueing a follow-up turn while t1 is RUNNING requires allow_queue=True
            with self.assertRaises(SessionStateConflict):
                store.start_turn(session.session_id, "unqueued follow-up")
            with self.assertRaises(SessionStateConflict):
                store.start_turn(
                    session.session_id,
                    "stale version queue",
                    allow_queue=True,
                    expected_version=running_session.version + 5,
                )

            t2 = store.start_turn(
                session.session_id,
                "queued follow-up",
                allow_queue=True,
                expected_version=running_session.version,
                idempotency_key="queue-key-2",
            )
            t2_replay = store.start_turn(
                session.session_id,
                "queued follow-up",
                allow_queue=True,
                idempotency_key="queue-key-2",
            )
            self.assertEqual(t2.turn_id, t2_replay.turn_id)
            self.assertEqual(len(store.list_turns(session_id=session.session_id)), 2)

            # Steer t1 with expected_version and idempotency_key
            current_t1 = store.get_turn(t1.turn_id)
            steer_item = store.steer_turn(
                session.session_id,
                t1.turn_id,
                "adjust focus",
                expected_version=current_t1.version,
                idempotency_key="steer-key-1",
            )
            steer_replay = store.steer_turn(
                session.session_id,
                t1.turn_id,
                "adjust focus",
                expected_version=1,
                idempotency_key="steer-key-1",
            )
            self.assertEqual(steer_item.item_id, steer_replay.item_id)
            with self.assertRaises(SessionStateConflict):
                store.steer_turn(
                    session.session_id,
                    t1.turn_id,
                    "stale steer",
                    expected_version=current_t1.version,
                )
        finally:
            store.close()

    def test_cursor_gap_detection_on_event_page(self) -> None:
        store = AgentSessionStore()
        try:
            session = store.create_session("mesh.agent")
            store.record_event(session.session_id, "step.one", {"n": 1})
            store.record_event(session.session_id, "step.two", {"n": 2})
            ahead_page = store.read_event_page(session.session_id, after_sequence=50)
            self.assertTrue(ahead_page.cursor_gap)
            self.assertEqual(ahead_page.gap_reason, "cursor_ahead_of_head")
            self.assertEqual(ahead_page.latest_sequence, 3)

            # Simulate compacted/deleted sequence 2 to verify missing_sequences detection
            with store._transaction() as conn:
                conn.execute(
                    "DELETE FROM agent_events WHERE session_id = ? AND sequence = 2",
                    (session.session_id,),
                )
            gap_page = store.read_event_page(session.session_id, after_sequence=1)
            self.assertTrue(gap_page.cursor_gap)
            self.assertEqual(gap_page.gap_reason, "missing_sequences")
            self.assertEqual(gap_page.events[0].sequence, 3)
        finally:
            store.close()


if __name__ == "__main__":
    unittest.main()
