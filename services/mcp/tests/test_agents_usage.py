"""Contract tests for durable, idempotent usage accounting."""
from __future__ import annotations

import sqlite3
import tempfile
import unittest
from pathlib import Path

from services.mcp.platform.usage import (
    UsageBudget,
    UsageConflict,
    UsageDelta,
    UsageLedger,
    UsageLimitExceeded,
    UsageQuota,
)


class TestUsageLedger(unittest.TestCase):
    def test_idempotency_budget_and_restart(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            database = Path(directory) / "usage.sqlite3"
            ledger = UsageLedger(database)
            delta = UsageDelta(
                session_id="sess_1",
                turn_id="turn_1",
                principal_id="user_1",
                prompt_tokens=10,
                completion_tokens=5,
                tool_calls=1,
            )
            first = ledger.record(delta, idempotency_key="turn:sess_1:turn_1", budget=UsageBudget(prompt_tokens=20))
            replay = ledger.record(delta, idempotency_key="turn:sess_1:turn_1", budget=UsageBudget(prompt_tokens=20))
            self.assertEqual(first.usage_id, replay.usage_id)
            with self.assertRaises(UsageConflict):
                ledger.record(
                    UsageDelta(session_id="sess_1", turn_id="turn_2", prompt_tokens=11),
                    idempotency_key="turn:sess_1:turn_1",
                )
            with self.assertRaises(UsageLimitExceeded):
                ledger.record(
                    UsageDelta(session_id="sess_1", turn_id="turn_2", prompt_tokens=11),
                    idempotency_key="turn:sess_1:turn_2",
                    budget=UsageBudget(prompt_tokens=20),
                )
            self.assertEqual(ledger.totals(session_id="sess_1").prompt_tokens, 10)
            metered = ledger.record(
                UsageDelta(
                    session_id="sess_1",
                    turn_id="turn_3",
                    gpu_milliseconds=5,
                    vram_byte_seconds=9,
                    network_bytes=12,
                ),
                idempotency_key="turn:sess_1:turn_3",
                budget=UsageBudget(gpu_milliseconds=5, vram_byte_seconds=9, network_bytes=12),
            )
            self.assertEqual(metered.delta.network_bytes, 12)
            ledger.close()
            reopened = UsageLedger(database)
            try:
                self.assertEqual(reopened.totals(principal_id="user_1").completion_tokens, 5)
            finally:
                reopened.close()

    def test_lifetime_principal_and_tenant_quotas_are_atomic_and_idempotent(self) -> None:
        ledger = UsageLedger()
        try:
            ledger.set_quota(UsageQuota("principal", "user_1", "lifetime", UsageBudget(prompt_tokens=10)))
            ledger.set_quota(UsageQuota("tenant", "tenant_1", "lifetime", UsageBudget(network_bytes=5)))
            delta = UsageDelta(
                session_id="sess_1",
                turn_id="turn_1",
                principal_id="user_1",
                tenant_id="tenant_1",
                prompt_tokens=6,
                network_bytes=5,
            )
            ledger.record(delta, idempotency_key="quota:turn_1")
            ledger.record(delta, idempotency_key="quota:turn_1")
            self.assertEqual(ledger.totals(tenant_id="tenant_1").network_bytes, 5)
            with self.assertRaises(UsageLimitExceeded):
                ledger.record(
                    UsageDelta(
                        session_id="sess_1",
                        turn_id="turn_2",
                        principal_id="user_1",
                        tenant_id="tenant_1",
                        prompt_tokens=5,
                    ),
                    idempotency_key="quota:turn_2",
                )
            with self.assertRaises(UsageLimitExceeded):
                ledger.record(
                    UsageDelta(
                        session_id="sess_2",
                        turn_id="turn_3",
                        principal_id="user_2",
                        tenant_id="tenant_1",
                        network_bytes=1,
                    ),
                    idempotency_key="quota:turn_3",
                )
            self.assertEqual(len(ledger.list_quotas()), 2)
            self.assertTrue(ledger.remove_quota(scope_type="tenant", scope_id="tenant_1", period="lifetime"))
        finally:
            ledger.close()

    def test_existing_usage_database_migrates_tenant_column(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            database = Path(directory) / "legacy-usage.sqlite3"
            connection = sqlite3.connect(database)
            connection.execute(
                """CREATE TABLE usage_records (
                    usage_id TEXT PRIMARY KEY,
                    idempotency_key TEXT UNIQUE NOT NULL,
                    recorded_at REAL NOT NULL,
                    session_id TEXT NOT NULL,
                    turn_id TEXT NOT NULL,
                    principal_id TEXT NOT NULL,
                    node_id TEXT NOT NULL,
                    model_id TEXT NOT NULL,
                    prompt_tokens INTEGER NOT NULL,
                    completion_tokens INTEGER NOT NULL,
                    tool_calls INTEGER NOT NULL,
                    cpu_milliseconds INTEGER NOT NULL,
                    gpu_milliseconds INTEGER NOT NULL,
                    vram_byte_seconds INTEGER NOT NULL,
                    network_bytes INTEGER NOT NULL,
                    artifact_bytes INTEGER NOT NULL,
                    external_cost_micros INTEGER NOT NULL,
                    fingerprint TEXT NOT NULL
                )"""
            )
            connection.commit()
            connection.close()
            ledger = UsageLedger(database)
            try:
                ledger.record(UsageDelta(session_id="sess_1", turn_id="turn_1"), idempotency_key="legacy:turn_1")
                columns = {
                    row["name"]
                    for row in ledger._connection.execute("PRAGMA table_info(usage_records)").fetchall()
                }
                self.assertIn("tenant_id", columns)
            finally:
                ledger.close()


if __name__ == "__main__":
    unittest.main()
