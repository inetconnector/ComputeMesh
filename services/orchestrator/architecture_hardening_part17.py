"""ComputeMesh Architecture Hardening (Part 17)

Enforces invariants:
- "placement has revision;" (Reliability principles)
- "rate/budget limits;" (Public-alpha readiness)
- "node workload boundary;" (Public-alpha readiness)
"""

import sqlite3
import time
from typing import Any, Dict, Optional

class HardeningPart17Error(RuntimeError):
    """Base exception for Part 17 invariant violations."""
    pass

class PlacementRevisionError(HardeningPart17Error):
    """Raised when placement revision checks fail."""
    pass

class RateBudgetLimitError(HardeningPart17Error):
    """Raised when a user exceeds their rate or budget limits."""
    pass

class WorkloadBoundaryError(HardeningPart17Error):
    """Raised when a node violates its allowed workload boundaries."""
    pass

class PlacementRevisionEnforcer:
    """Enforces: placement has revision."""

    def __init__(self, db: sqlite3.Connection):
        self._db = db
        self._db.execute(
            "CREATE TABLE IF NOT EXISTS placement_revisions ("
            "placement_id TEXT PRIMARY KEY, "
            "revision INTEGER NOT NULL"
            ")"
        )

    def create_placement(self, placement_id: str) -> None:
        try:
            self._db.execute(
                "INSERT INTO placement_revisions (placement_id, revision) VALUES (?, 1)",
                (placement_id,)
            )
        except sqlite3.IntegrityError:
            raise PlacementRevisionError(f"Placement {placement_id} already exists.")

    def update_placement(self, placement_id: str, expected_revision: int) -> int:
        """Updates a placement and returns the new revision if successful."""
        cursor = self._db.cursor()
        cursor.execute("SELECT revision FROM placement_revisions WHERE placement_id = ?", (placement_id,))
        row = cursor.fetchone()
        if not row:
            raise PlacementRevisionError(f"Placement {placement_id} not found.")

        current_revision = row[0]
        if current_revision != expected_revision:
            raise PlacementRevisionError(
                f"Revision mismatch for placement {placement_id}. Expected {expected_revision}, got {current_revision}."
            )

        new_revision = current_revision + 1
        cursor.execute(
            "UPDATE placement_revisions SET revision = ? WHERE placement_id = ? AND revision = ?",
            (new_revision, placement_id, expected_revision)
        )
        if cursor.rowcount != 1:
            raise PlacementRevisionError(f"Concurrent update failed for placement {placement_id}.")
        return new_revision


class RateBudgetLimitEnforcer:
    """Enforces: rate/budget limits."""

    def __init__(self, db: sqlite3.Connection):
        self._db = db
        self._db.execute(
            "CREATE TABLE IF NOT EXISTS budget_limits ("
            "user_id TEXT PRIMARY KEY, "
            "budget_spent INTEGER NOT NULL, "
            "budget_limit INTEGER NOT NULL, "
            "last_request_time REAL NOT NULL"
            ")"
        )

    def set_limit(self, user_id: str, budget_limit: int) -> None:
        self._db.execute(
            "INSERT INTO budget_limits (user_id, budget_spent, budget_limit, last_request_time) "
            "VALUES (?, 0, ?, 0.0) "
            "ON CONFLICT(user_id) DO UPDATE SET budget_limit=excluded.budget_limit",
            (user_id, budget_limit)
        )

    def consume_budget(self, user_id: str, amount: int, current_time: float, min_interval: float = 0.1) -> None:
        cursor = self._db.cursor()
        cursor.execute(
            "SELECT budget_spent, budget_limit, last_request_time FROM budget_limits WHERE user_id = ?",
            (user_id,)
        )
        row = cursor.fetchone()
        if not row:
            raise RateBudgetLimitError(f"No budget limit set for user {user_id}.")

        budget_spent, budget_limit, last_request_time = row

        if current_time - last_request_time < min_interval:
            raise RateBudgetLimitError(f"Rate limit exceeded for user {user_id}.")

        if budget_spent + amount > budget_limit:
            raise RateBudgetLimitError(f"Budget exceeded for user {user_id}. Attempted to spend {amount}, available {budget_limit - budget_spent}.")

        cursor.execute(
            "UPDATE budget_limits SET budget_spent = budget_spent + ?, last_request_time = ? WHERE user_id = ?",
            (amount, current_time, user_id)
        )


class NodeWorkloadBoundaryEnforcer:
    """Enforces: node workload boundary."""

    def __init__(self, db: sqlite3.Connection):
        self._db = db
        self._db.execute(
            "CREATE TABLE IF NOT EXISTS node_workload_boundaries ("
            "node_id TEXT PRIMARY KEY, "
            "allowed_models TEXT NOT NULL, "
            "max_memory_bytes INTEGER NOT NULL"
            ")"
        )

    def set_boundary(self, node_id: str, allowed_models: list[str], max_memory_bytes: int) -> None:
        models_str = ",".join(allowed_models)
        self._db.execute(
            "INSERT INTO node_workload_boundaries (node_id, allowed_models, max_memory_bytes) "
            "VALUES (?, ?, ?) "
            "ON CONFLICT(node_id) DO UPDATE SET allowed_models=excluded.allowed_models, max_memory_bytes=excluded.max_memory_bytes",
            (node_id, models_str, max_memory_bytes)
        )

    def validate_workload(self, node_id: str, model_id: str, required_memory_bytes: int) -> None:
        cursor = self._db.cursor()
        cursor.execute(
            "SELECT allowed_models, max_memory_bytes FROM node_workload_boundaries WHERE node_id = ?",
            (node_id,)
        )
        row = cursor.fetchone()
        if not row:
            raise WorkloadBoundaryError(f"No workload boundary defined for node {node_id}.")

        allowed_models_str, max_memory_bytes = row
        allowed_models = allowed_models_str.split(",") if allowed_models_str else []

        if model_id not in allowed_models:
            raise WorkloadBoundaryError(f"Model {model_id} is not allowed on node {node_id}. Allowed: {allowed_models}")

        if required_memory_bytes > max_memory_bytes:
            raise WorkloadBoundaryError(f"Memory requirement {required_memory_bytes} bytes exceeds boundary limit {max_memory_bytes} bytes on node {node_id}.")
