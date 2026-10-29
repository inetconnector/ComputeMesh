"""ComputeMesh Architecture Hardening (Part 14)

Enforces invariants:
- "ambiguous completion is reconciled before settlement;"
- "no silent corruption;"
- "billing is neutral for platform-caused duplicate execution unless policy explicitly assigns cost."
"""

import sqlite3
from typing import Any, Dict, Optional


class HardeningPart14Error(RuntimeError):
    """Base exception for Part 14 invariant violations."""
    pass


class AmbiguousCompletionError(HardeningPart14Error):
    """Raised when an ambiguous completion is settled before reconciliation."""
    pass


class SilentCorruptionError(HardeningPart14Error):
    """Raised when silent corruption is detected (e.g., digest mismatch)."""
    pass


class BillingNeutralityError(HardeningPart14Error):
    """Raised when billing is not neutral for platform-caused duplicate execution."""
    pass


class AmbiguousCompletionEnforcer:
    """Enforces: ambiguous completion is reconciled before settlement."""

    def __init__(self, db: sqlite3.Connection):
        self._db = db
        self._db.execute(
            "CREATE TABLE IF NOT EXISTS completion_status ("
            "job_id TEXT PRIMARY KEY, "
            "is_ambiguous BOOLEAN NOT NULL, "
            "is_reconciled BOOLEAN NOT NULL"
            ")"
        )

    def mark_completion(self, job_id: str, is_ambiguous: bool) -> None:
        self._db.execute(
            "INSERT INTO completion_status (job_id, is_ambiguous, is_reconciled) VALUES (?, ?, ?) "
            "ON CONFLICT(job_id) DO UPDATE SET is_ambiguous=excluded.is_ambiguous, is_reconciled=False",
            (job_id, is_ambiguous, False)
        )

    def reconcile_completion(self, job_id: str) -> None:
        self._db.execute(
            "UPDATE completion_status SET is_reconciled=1 WHERE job_id=?",
            (job_id,)
        )

    def enforce_settlement_prerequisites(self, job_id: str) -> None:
        row = self._db.execute(
            "SELECT is_ambiguous, is_reconciled FROM completion_status WHERE job_id=?",
            (job_id,)
        ).fetchone()
        if not row:
            raise AmbiguousCompletionError(
                f"Job {job_id} has no completion record. Settlement requires an explicitly recorded completion status."
            )
        is_ambiguous, is_reconciled = row
        if is_ambiguous and not is_reconciled:
            raise AmbiguousCompletionError(
                f"Job {job_id} has an ambiguous completion that must be reconciled before settlement."
            )


class SilentCorruptionEnforcer:
    """Enforces: no silent corruption."""

    def verify_integrity(self, expected_digest: str, actual_digest: str, component_id: str) -> None:
        if expected_digest != actual_digest:
            raise SilentCorruptionError(
                f"Integrity check failed for {component_id}: expected {expected_digest}, got {actual_digest}. "
                "Silent corruption is not allowed."
            )


class BillingNeutralityEnforcer:
    """Enforces: billing is neutral for platform-caused duplicate execution unless policy explicitly assigns cost."""

    def __init__(self, db: sqlite3.Connection):
        self._db = db
        self._db.execute(
            "CREATE TABLE IF NOT EXISTS job_billing ("
            "job_id TEXT, "
            "execution_id TEXT, "
            "is_platform_duplicate BOOLEAN, "
            "policy_assigns_cost BOOLEAN, "
            "amount_billed INTEGER, "
            "PRIMARY KEY (job_id, execution_id)"
            ")"
        )

    def record_execution_billing(
        self,
        job_id: str,
        execution_id: str,
        is_platform_duplicate: bool,
        policy_assigns_cost: bool,
        amount_billed: int
    ) -> None:
        if is_platform_duplicate and amount_billed > 0 and not policy_assigns_cost:
            raise BillingNeutralityError(
                f"Platform-caused duplicate execution {execution_id} for job {job_id} must be "
                "billing-neutral unless policy explicitly assigns cost."
            )

        self._db.execute(
            "INSERT INTO job_billing (job_id, execution_id, is_platform_duplicate, policy_assigns_cost, amount_billed) "
            "VALUES (?, ?, ?, ?, ?) "
            "ON CONFLICT(job_id, execution_id) DO UPDATE SET "
            "is_platform_duplicate=excluded.is_platform_duplicate, "
            "policy_assigns_cost=excluded.policy_assigns_cost, "
            "amount_billed=excluded.amount_billed",
            (job_id, execution_id, is_platform_duplicate, policy_assigns_cost, amount_billed)
        )
