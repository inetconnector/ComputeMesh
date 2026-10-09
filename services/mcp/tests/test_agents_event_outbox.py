"""Tests for restart-safe durable agent event delivery."""
from __future__ import annotations

import tempfile
import threading
import time
import unittest
from pathlib import Path

from services.mcp.config import MCPConfig
from services.mcp.platform.event_outbox import (
    AgentEventOutboxDispatcher,
    EventOutboxDispatchError,
)
from services.mcp.platform.runtime import AgentsPlatformRuntime
from services.mcp.platform.session import AgentSessionStore


class TestAgentEventOutboxDispatcher(unittest.TestCase):
    def test_successful_delivery_acknowledges_the_claim(self) -> None:
        store = AgentSessionStore()
        try:
            session = store.create_session("mesh.agent")
            store.record_event(session.session_id, "demo.event", {"value": 1})
            received = []
            dispatcher = AgentEventOutboxDispatcher(store, "consumer-a", received.append)
            stats = dispatcher.dispatch_once()
            self.assertEqual(stats.claimed, 2)
            self.assertEqual(stats.delivered, 2)
            self.assertEqual(stats.failed, 0)
            self.assertEqual([event.event_type for event in received], ["session.created", "demo.event"])
            self.assertEqual(store.pending_events(), [])
        finally:
            store.close()

    def test_sink_failure_releases_event_and_allows_retry(self) -> None:
        store = AgentSessionStore()
        try:
            session = store.create_session("mesh.agent")
            store.record_event(session.session_id, "demo.event", {"value": 1})
            attempts = []

            def sink(event):
                attempts.append(event.event_id)
                if len(attempts) == 1:
                    raise RuntimeError("temporary sink failure")

            dispatcher = AgentEventOutboxDispatcher(store, "consumer-a", sink, batch_size=1)
            first = dispatcher.dispatch_once()
            self.assertEqual((first.claimed, first.delivered, first.released, first.failed), (1, 0, 1, 1))
            second = dispatcher.dispatch_once()
            self.assertEqual((second.claimed, second.delivered, second.released, second.failed), (1, 1, 0, 0))
            self.assertEqual(dispatcher.last_error, "RuntimeError: temporary sink failure")
        finally:
            store.close()

    def test_crashed_consumer_claim_is_recovered_by_another_consumer(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = AgentSessionStore(Path(directory) / "sessions.sqlite3")
            try:
                session = store.create_session("mesh.agent")
                store.record_event(session.session_id, "demo.event", {"value": 1})
                abandoned = store.claim_pending_events("consumer-a", limit=1, lease_seconds=0.01)
                self.assertEqual(len(abandoned), 1)
                time.sleep(0.03)
                received = []
                dispatcher = AgentEventOutboxDispatcher(store, "consumer-b", received.append, batch_size=1)
                stats = dispatcher.dispatch_once()
                self.assertEqual(stats.delivered, 1)
                self.assertEqual(received[0].event_id, abandoned[0].event_id)
            finally:
                store.close()

    def test_supervised_polling_stops_cleanly(self) -> None:
        store = AgentSessionStore()
        try:
            session = store.create_session("mesh.agent")
            store.record_event(session.session_id, "demo.event", {"value": 1})
            delivered = threading.Event()
            dispatcher = AgentEventOutboxDispatcher(
                store,
                "consumer-thread",
                lambda _event: delivered.set(),
                batch_size=1,
                poll_seconds=0.01,
            )
            thread = dispatcher.start()
            self.assertTrue(delivered.wait(1.0))
            dispatcher.close(timeout=1.0)
            self.assertFalse(thread.is_alive())
        finally:
            store.close()

    def test_invalid_configuration_fails_closed(self) -> None:
        store = AgentSessionStore()
        try:
            with self.assertRaises(EventOutboxDispatchError):
                AgentEventOutboxDispatcher(store, "consumer-a", lambda _event: None, batch_size=0)
            with self.assertRaises(ValueError):
                AgentEventOutboxDispatcher(store, "invalid consumer", lambda _event: None)
        finally:
            store.close()

    def test_runtime_factory_binds_the_runtime_session_store(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            config = MCPConfig(
                agents_platform_enabled=True,
                agents_platform_skill_roots="",
                agents_platform_registry_db=str(root / "registry.sqlite3"),
                agents_platform_memory_db=str(root / "memory.sqlite3"),
                agents_platform_audit_log=str(root / "audit.jsonl"),
                agents_platform_project_state=str(root / "project.json"),
                agents_platform_session_db=str(root / "sessions.sqlite3"),
                agents_platform_node_registry_db=str(root / "nodes.sqlite3"),
                agents_platform_lease_db=str(root / "leases.sqlite3"),
                agents_platform_artifact_root=str(root / "artifacts"),
                agents_platform_artifact_db=str(root / "artifacts.sqlite3"),
                agents_platform_usage_db=str(root / "usage.sqlite3"),
                agents_platform_trace_db=str(root / "traces.sqlite3"),
            )
            runtime = AgentsPlatformRuntime(config=config, repo_root=root)
            try:
                self.assertIsNotNone(runtime.session_store)
                received = []
                dispatcher = runtime.build_event_outbox_dispatcher(
                    consumer_id="runtime-consumer",
                    sink=received.append,
                    batch_size=1,
                )
                session = runtime.session_store.create_session("mesh.agent")
                stats = dispatcher.dispatch_once()
                self.assertEqual(stats.delivered, 1)
                self.assertEqual(received[0].session_id, session.session_id)
            finally:
                runtime.close()


if __name__ == "__main__":
    unittest.main()
