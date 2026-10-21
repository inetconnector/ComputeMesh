"""ComputeMesh Architecture Hardening (Part 11)

Enforces invariants:
- "Monetary data uses integer fixed units, never floating-point." (Data Model Principles)
- "Financial ledger entries are append-only." (ARCHITECTURE.md 12.1)
- "Job state transitions use optimistic concurrency or equivalent revision checks." (ARCHITECTURE.md 12.1)
"""

import sqlite3
import time
from typing import Any, Dict, List

class HardeningPart11Error(RuntimeError):
    """Base exception for Part 11 invariant violations."""
    pass

class MonetaryUnitError(HardeningPart11Error):
    """Raised when monetary data is not an integer."""
    pass

class AppendOnlyLedgerError(HardeningPart11Error):
    """Raised when an append-only ledger invariant is violated."""
    pass

class OptimisticConcurrencyError(HardeningPart11Error):
    """Raised when an optimistic concurrency check fails."""
    pass


class StrictLedgerManager:
    """
    Enforces:
    1. Financial ledger entries are append-only.
    2. Monetary data uses integer fixed units, never floating-point.
    """
    def __init__(self, db_path: str = ":memory:"):
        self.conn = sqlite3.connect(db_path)
        self._initialize_schema()

    def _initialize_schema(self):
        self.conn.execute('''
            CREATE TABLE IF NOT EXISTS ledger (
                entry_id TEXT PRIMARY KEY,
                account TEXT NOT NULL,
                amount INTEGER NOT NULL,
                timestamp REAL NOT NULL
            )
        ''')
        # Database-level triggers to enforce append-only property
        self.conn.execute('''
            CREATE TRIGGER IF NOT EXISTS prevent_ledger_update
            BEFORE UPDATE ON ledger
            BEGIN
                SELECT RAISE(ABORT, 'Financial ledger entries are append-only. Updates are strictly forbidden.');
            END;
        ''')
        self.conn.execute('''
            CREATE TRIGGER IF NOT EXISTS prevent_ledger_delete
            BEFORE DELETE ON ledger
            BEGIN
                SELECT RAISE(ABORT, 'Financial ledger entries are append-only. Deletions are strictly forbidden.');
            END;
        ''')
        self.conn.commit()

    def append_entry(self, entry_id: str, account: str, amount: Any) -> None:
        if isinstance(amount, float):
            raise MonetaryUnitError("Monetary amount MUST NOT be a floating-point number.")
        if not isinstance(amount, int):
            raise MonetaryUnitError("Monetary amount MUST be an integer.")

        try:
            self.conn.execute(
                "INSERT INTO ledger (entry_id, account, amount, timestamp) VALUES (?, ?, ?, ?)",
                (entry_id, account, amount, time.time())
            )
            self.conn.commit()
        except sqlite3.IntegrityError as e:
            if "UNIQUE constraint failed" in str(e) or "PRIMARY KEY constraint failed" in str(e):
                raise AppendOnlyLedgerError(f"Ledger entry {entry_id} already exists. Financial ledger entries are append-only.")
            raise

    def get_entries(self) -> List[Dict[str, Any]]:
        cursor = self.conn.cursor()
        cursor.execute("SELECT entry_id, account, amount, timestamp FROM ledger ORDER BY timestamp ASC")
        return [
            {"entry_id": row[0], "account": row[1], "amount": row[2], "timestamp": row[3]}
            for row in cursor.fetchall()
        ]

    def _attempt_illegal_update(self, entry_id: str, new_amount: int) -> None:
        """Helper to demonstrate trigger enforcement."""
        try:
            self.conn.execute("UPDATE ledger SET amount = ? WHERE entry_id = ?", (new_amount, entry_id))
            self.conn.commit()
        except sqlite3.IntegrityError as e:
            raise AppendOnlyLedgerError(str(e))
        except sqlite3.OperationalError as e:
            raise AppendOnlyLedgerError(str(e))

    def _attempt_illegal_delete(self, entry_id: str) -> None:
        """Helper to demonstrate trigger enforcement."""
        try:
            self.conn.execute("DELETE FROM ledger WHERE entry_id = ?", (entry_id,))
            self.conn.commit()
        except sqlite3.IntegrityError as e:
            raise AppendOnlyLedgerError(str(e))
        except sqlite3.OperationalError as e:
            raise AppendOnlyLedgerError(str(e))


class RevisionedJobManager:
    """
    Enforces: Job state transitions use optimistic concurrency or equivalent revision checks.
    """
    def __init__(self, db_path: str = ":memory:"):
        self.conn = sqlite3.connect(db_path)
        self._initialize_schema()

    def _initialize_schema(self):
        self.conn.execute('''
            CREATE TABLE IF NOT EXISTS jobs (
                job_id TEXT PRIMARY KEY,
                state TEXT NOT NULL,
                revision INTEGER NOT NULL
            )
        ''')
        self.conn.commit()

    def create_job(self, job_id: str, initial_state: str) -> None:
        try:
            self.conn.execute(
                "INSERT INTO jobs (job_id, state, revision) VALUES (?, ?, 1)",
                (job_id, initial_state)
            )
            self.conn.commit()
        except sqlite3.IntegrityError:
            raise OptimisticConcurrencyError(f"Job {job_id} already exists.")

    def transition_state(self, job_id: str, expected_revision: int, new_state: str) -> None:
        cursor = self.conn.cursor()
        cursor.execute("SELECT revision FROM jobs WHERE job_id = ?", (job_id,))
        row = cursor.fetchone()
        if not row:
            raise OptimisticConcurrencyError(f"Job {job_id} not found.")

        current_revision = row[0]
        if current_revision != expected_revision:
            raise OptimisticConcurrencyError(
                f"Optimistic concurrency failure: expected revision {expected_revision}, but current is {current_revision}."
            )

        cursor.execute(
            "UPDATE jobs SET state = ?, revision = revision + 1 WHERE job_id = ? AND revision = ?",
            (new_state, job_id, expected_revision)
        )
        if cursor.rowcount != 1:
            # Another transaction might have modified it in the split second
            raise OptimisticConcurrencyError("Concurrency conflict during update.")
        self.conn.commit()

    def get_job(self, job_id: str) -> Dict[str, Any]:
        cursor = self.conn.cursor()
        cursor.execute("SELECT job_id, state, revision FROM jobs WHERE job_id = ?", (job_id,))
        row = cursor.fetchone()
        if not row:
            raise OptimisticConcurrencyError(f"Job {job_id} not found.")
        return {"job_id": row[0], "state": row[1], "revision": row[2]}
