"""Persistent node reservation leases for capability-aware agent execution."""
from __future__ import annotations

import hashlib
import json
import re
import sqlite3
import threading
import time
import uuid
from contextlib import contextmanager
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any, Callable, Iterator, Mapping

from .node_registry import NodeLifecycle, NodeRegistry


class ReservationError(RuntimeError):
    """Base error for node reservation failures."""


class ReservationDenied(ReservationError):
    """Raised when a node cannot satisfy a reservation request."""


class ReservationConflict(ReservationError):
    """Raised when an idempotency key is reused with different semantics."""


class LeaseState(str, Enum):
    ACTIVE = "active"
    RELEASED = "released"
    EXPIRED = "expired"
    REVOKED = "revoked"


@dataclass(frozen=True)
class NodeLease:
    lease_id: str
    node_id: str
    session_id: str
    turn_id: str
    model_id: str
    requested_slots: int
    capacity_limit: int
    status: LeaseState
    idempotency_key: str
    request_fingerprint: str
    issued_at: float
    expires_at: float
    version: int
    updated_at: float

    def to_dict(self) -> dict[str, Any]:
        return {
            "lease_id": self.lease_id,
            "node_id": self.node_id,
            "session_id": self.session_id,
            "turn_id": self.turn_id,
            "model_id": self.model_id,
            "requested_slots": self.requested_slots,
            "capacity_limit": self.capacity_limit,
            "status": self.status.value,
            "idempotency_key": self.idempotency_key,
            "issued_at": self.issued_at,
            "expires_at": self.expires_at,
            "version": self.version,
            "updated_at": self.updated_at,
        }


def _valid_identifier(value: str) -> bool:
    return bool(re.fullmatch(r"[A-Za-z0-9_.:-]{1,160}", str(value)))


class NodeLeaseStore:
    """SQLite-backed capacity reservations bound to a NodeRegistry."""

    def __init__(
        self,
        path: str | Path = ":memory:",
        *,
        node_registry: NodeRegistry,
        event_sink: Callable[[str, Mapping[str, Any]], None] | None = None,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self.path = Path(path)
        if str(path) != ":memory:":
            self.path.parent.mkdir(parents=True, exist_ok=True)
        self.node_registry = node_registry
        self.event_sink = event_sink
        self.clock = clock
        self._lock = threading.RLock()
        self._connection = sqlite3.connect(str(path), check_same_thread=False, timeout=30.0)
        self._connection.row_factory = sqlite3.Row
        self._connection.execute("PRAGMA busy_timeout = 30000")
        if str(path) != ":memory:":
            self._connection.execute("PRAGMA journal_mode = WAL")
        self._connection.execute("PRAGMA synchronous = NORMAL")
        self._create_schema()

    def _create_schema(self) -> None:
        with self._transaction() as connection:
            connection.execute(
                """CREATE TABLE IF NOT EXISTS node_leases (
                    lease_id TEXT PRIMARY KEY,
                    node_id TEXT NOT NULL,
                    session_id TEXT NOT NULL,
                    turn_id TEXT NOT NULL,
                    model_id TEXT NOT NULL,
                    requested_slots INTEGER NOT NULL,
                    capacity_limit INTEGER NOT NULL,
                    status TEXT NOT NULL,
                    idempotency_key TEXT NOT NULL,
                    request_fingerprint TEXT NOT NULL,
                    issued_at REAL NOT NULL,
                    expires_at REAL NOT NULL,
                    version INTEGER NOT NULL DEFAULT 1,
                    updated_at REAL NOT NULL,
                    UNIQUE(session_id, idempotency_key)
                )"""
            )
            connection.execute("CREATE INDEX IF NOT EXISTS node_leases_active_idx ON node_leases(node_id, status, expires_at)")

    @contextmanager
    def _transaction(self) -> Iterator[sqlite3.Connection]:
        with self._lock:
            try:
                self._connection.execute("BEGIN IMMEDIATE")
                yield self._connection
                self._connection.commit()
            except Exception:
                self._connection.rollback()
                raise

    @staticmethod
    def _lease(row: sqlite3.Row) -> NodeLease:
        return NodeLease(
            lease_id=str(row["lease_id"]),
            node_id=str(row["node_id"]),
            session_id=str(row["session_id"]),
            turn_id=str(row["turn_id"]),
            model_id=str(row["model_id"]),
            requested_slots=int(row["requested_slots"]),
            capacity_limit=int(row["capacity_limit"]),
            status=LeaseState(str(row["status"])),
            idempotency_key=str(row["idempotency_key"]),
            request_fingerprint=str(row["request_fingerprint"]),
            issued_at=float(row["issued_at"]),
            expires_at=float(row["expires_at"]),
            version=int(row["version"]),
            updated_at=float(row["updated_at"]),
        )

    def _emit(self, event_type: str, payload: Mapping[str, Any]) -> None:
        if self.event_sink is not None:
            self.event_sink(event_type, dict(payload))

    @staticmethod
    def _fingerprint(*, node_id: str, turn_id: str, model_id: str, requested_slots: int, capacity_limit: int, ttl_seconds: int) -> str:
        value = {
            "node_id": node_id,
            "turn_id": turn_id,
            "model_id": model_id,
            "requested_slots": requested_slots,
            "capacity_limit": capacity_limit,
            "ttl_seconds": ttl_seconds,
        }
        return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()

    def _expire_locked(self, connection: sqlite3.Connection, now: float, *, node_id: str | None = None) -> None:
        query = "UPDATE node_leases SET status = ?, version = version + 1, updated_at = ? WHERE status = ? AND expires_at <= ?"
        params: list[Any] = [LeaseState.EXPIRED.value, now, LeaseState.ACTIVE.value, now]
        if node_id is not None:
            query += " AND node_id = ?"
            params.append(node_id)
        rows = connection.execute("SELECT lease_id, node_id FROM node_leases WHERE status = ? AND expires_at <= ?" + (" AND node_id = ?" if node_id is not None else ""), [LeaseState.ACTIVE.value, now] + ([node_id] if node_id is not None else [])).fetchall()
        connection.execute(query, params)
        for row in rows:
            self._emit("node.lease.expired", {"lease_id": str(row["lease_id"]), "node_id": str(row["node_id"])})

    def reserve(
        self,
        *,
        node_id: str,
        session_id: str,
        turn_id: str,
        model_id: str,
        requested_slots: int = 1,
        capacity_limit: int = 1,
        ttl_seconds: int = 300,
        idempotency_key: str,
    ) -> NodeLease:
        for value, label in ((node_id, "node_id"), (session_id, "session_id"), (turn_id, "turn_id"), (idempotency_key, "idempotency_key")):
            if not _valid_identifier(str(value)):
                raise ValueError(f"invalid {label}")
        if not 1 <= len(str(model_id)) <= 256:
            raise ValueError("model_id must be 1..256 characters")
        if not 1 <= int(requested_slots) <= 1_000_000 or not 1 <= int(capacity_limit) <= 1_000_000 or int(requested_slots) > int(capacity_limit):
            raise ValueError("requested_slots must fit within capacity_limit")
        if not 1 <= int(ttl_seconds) <= 7 * 24 * 3600:
            raise ValueError("ttl_seconds is outside the supported bound")
        node = self.node_registry.get(node_id)
        if node.status not in {NodeLifecycle.READY, NodeLifecycle.ACTIVE} or node.auth_required or not node.identity_key_id or not node.principal_id:
            raise ReservationDenied("node is not authenticated and routable")
        fingerprint = self._fingerprint(node_id=node_id, turn_id=turn_id, model_id=model_id, requested_slots=int(requested_slots), capacity_limit=int(capacity_limit), ttl_seconds=int(ttl_seconds))
        now = float(self.clock())
        with self._transaction() as connection:
            self._expire_locked(connection, now, node_id=node_id)
            existing = connection.execute("SELECT * FROM node_leases WHERE session_id = ? AND idempotency_key = ?", (session_id, idempotency_key)).fetchone()
            if existing is not None:
                prior = self._lease(existing)
                if prior.request_fingerprint != fingerprint:
                    raise ReservationConflict("idempotency key was reused with different reservation semantics")
                return prior
            used = int(connection.execute("SELECT COALESCE(SUM(requested_slots), 0) FROM node_leases WHERE node_id = ? AND status = ? AND expires_at > ?", (node_id, LeaseState.ACTIVE.value, now)).fetchone()[0])
            if used + int(requested_slots) > int(capacity_limit):
                raise ReservationDenied("node capacity is already reserved")
            lease_id = f"lease_{uuid.uuid4().hex}"
            expires_at = now + int(ttl_seconds)
            connection.execute(
                """INSERT INTO node_leases
                   (lease_id, node_id, session_id, turn_id, model_id, requested_slots,
                    capacity_limit, status, idempotency_key, request_fingerprint,
                    issued_at, expires_at, version, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1, ?)""",
                (lease_id, node_id, session_id, turn_id, model_id, int(requested_slots), int(capacity_limit), LeaseState.ACTIVE.value, idempotency_key, fingerprint, now, expires_at, now),
            )
            lease = self._lease(connection.execute("SELECT * FROM node_leases WHERE lease_id = ?", (lease_id,)).fetchone())
            self._emit("node.lease.created", {"lease_id": lease_id, "node_id": node_id, "session_id": session_id, "turn_id": turn_id, "requested_slots": int(requested_slots), "expires_at": expires_at})
            return lease

    def get(self, lease_id: str) -> NodeLease:
        with self._lock:
            row = self._connection.execute("SELECT * FROM node_leases WHERE lease_id = ?", (str(lease_id),)).fetchone()
        if row is None:
            raise KeyError(f"unknown node lease: {lease_id}")
        return self._lease(row)

    def renew(self, lease_id: str, *, ttl_seconds: int = 300) -> NodeLease:
        if not 1 <= int(ttl_seconds) <= 7 * 24 * 3600:
            raise ValueError("ttl_seconds is outside the supported bound")
        now = float(self.clock())
        with self._transaction() as connection:
            self._expire_locked(connection, now)
            row = connection.execute("SELECT * FROM node_leases WHERE lease_id = ?", (str(lease_id),)).fetchone()
            if row is None:
                raise KeyError(f"unknown node lease: {lease_id}")
            prior = self._lease(row)
            if prior.status is not LeaseState.ACTIVE:
                raise ReservationDenied(f"cannot renew lease in state {prior.status.value}")
            expires_at = now + int(ttl_seconds)
            connection.execute("UPDATE node_leases SET expires_at = ?, version = version + 1, updated_at = ? WHERE lease_id = ?", (expires_at, now, str(lease_id)))
            lease = self._lease(connection.execute("SELECT * FROM node_leases WHERE lease_id = ?", (str(lease_id),)).fetchone())
            self._emit("node.lease.renewed", {"lease_id": lease.lease_id, "node_id": lease.node_id, "expires_at": expires_at})
            return lease

    def _close(self, lease_id: str, target: LeaseState, reason: str) -> NodeLease:
        now = float(self.clock())
        with self._transaction() as connection:
            row = connection.execute("SELECT * FROM node_leases WHERE lease_id = ?", (str(lease_id),)).fetchone()
            if row is None:
                raise KeyError(f"unknown node lease: {lease_id}")
            prior = self._lease(row)
            if prior.status in {LeaseState.RELEASED, LeaseState.REVOKED, LeaseState.EXPIRED}:
                return prior
            connection.execute("UPDATE node_leases SET status = ?, version = version + 1, updated_at = ? WHERE lease_id = ?", (target.value, now, str(lease_id)))
            lease = self._lease(connection.execute("SELECT * FROM node_leases WHERE lease_id = ?", (str(lease_id),)).fetchone())
            self._emit(f"node.lease.{target.value}", {"lease_id": lease.lease_id, "node_id": lease.node_id, "reason": str(reason)[:256]})
            return lease

    def release(self, lease_id: str, *, reason: str = "released") -> NodeLease:
        return self._close(lease_id, LeaseState.RELEASED, reason)

    def revoke(self, lease_id: str, *, reason: str = "revoked") -> NodeLease:
        return self._close(lease_id, LeaseState.REVOKED, reason)

    def expire(self) -> int:
        now = float(self.clock())
        with self._transaction() as connection:
            before = int(connection.execute("SELECT COUNT(*) FROM node_leases WHERE status = ? AND expires_at <= ?", (LeaseState.ACTIVE.value, now)).fetchone()[0])
            self._expire_locked(connection, now)
            return before

    def active_for_node(self, node_id: str) -> tuple[NodeLease, ...]:
        now = float(self.clock())
        with self._transaction() as connection:
            self._expire_locked(connection, now, node_id=str(node_id))
            rows = connection.execute("SELECT * FROM node_leases WHERE node_id = ? AND status = ? ORDER BY issued_at", (str(node_id), LeaseState.ACTIVE.value)).fetchall()
            return tuple(self._lease(row) for row in rows)

    def close(self) -> None:
        with self._lock:
            self._connection.close()

    def __enter__(self) -> "NodeLeaseStore":
        return self

    def __exit__(self, *exc: Any) -> None:
        self.close()
