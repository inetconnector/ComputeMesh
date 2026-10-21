"""ComputeMesh Architecture Hardening (Part 13)

Enforces invariants:
- "retries are explicit attempts;"
- "commands expire;"
- "duplicate events dedupe;"
"""

import sqlite3
from typing import Any, Dict, Optional
import time


class HardeningPart13Error(RuntimeError):
    """Base exception for Part 13 invariant violations."""
    pass


class ImplicitRetryError(HardeningPart13Error):
    """Raised when a retry is attempted implicitly without being an explicit attempt."""
    pass


class CommandExpiredError(HardeningPart13Error):
    """Raised when an expired command is executed."""
    pass


class DuplicateEventError(HardeningPart13Error):
    """Raised when a duplicate event is not deduped."""
    pass


class ExplicitRetryEnforcer:
    """Enforces: retries are explicit attempts."""

    def __init__(self, db: sqlite3.Connection):
        self._db = db
        self._db.execute(
            "CREATE TABLE IF NOT EXISTS explicit_retries ("
            "entity_id TEXT PRIMARY KEY, "
            "last_attempt INTEGER NOT NULL"
            ")"
        )

    def register_attempt(self, job_id: str, attempt_number: int) -> None:
        row = self._db.execute("SELECT last_attempt FROM explicit_retries WHERE entity_id=?", (job_id,)).fetchone()
        last_attempt = row[0] if row else 0
        if attempt_number <= last_attempt:
            raise ImplicitRetryError(
                f"Retry for job {job_id} must be an explicit new attempt. "
                f"Attempt {attempt_number} is not greater than last attempt {last_attempt}."
            )
        self._db.execute(
            "INSERT INTO explicit_retries (entity_id, last_attempt) VALUES (?, ?) "
            "ON CONFLICT(entity_id) DO UPDATE SET last_attempt=excluded.last_attempt",
            (job_id, attempt_number)
        )


class CommandExpirationEnforcer:
    """Enforces: commands expire."""

    def validate_command(self, command: Dict[str, Any], current_time: float) -> None:
        if "expires_at" not in command:
            raise CommandExpiredError("Command must have an 'expires_at' timestamp.")

        if current_time >= command["expires_at"]:
            raise CommandExpiredError(f"Command expired at {command['expires_at']}, current time is {current_time}.")


class EventDeduplicator:
    """Enforces: duplicate events dedupe."""

    def __init__(self, db: sqlite3.Connection):
        self._db = db
        self._db.execute(
            "CREATE TABLE IF NOT EXISTS deduplicated_events ("
            "event_id TEXT PRIMARY KEY"
            ")"
        )

    def process_event(self, event_id: str) -> bool:
        """Returns True if event is new, False if it was a duplicate."""
        if not event_id:
            raise ValueError("Event must have an ID for deduplication.")
        try:
            self._db.execute("INSERT INTO deduplicated_events (event_id) VALUES (?)", (event_id,))
            return True
        except sqlite3.IntegrityError:
            return False
