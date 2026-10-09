"""Durable quarantine and capability inventory for discovered ComputeMesh nodes."""
from __future__ import annotations

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
from typing import Any, Iterator, Mapping, Sequence


class NodeRegistryError(RuntimeError):
    """Base error for durable node onboarding state."""


class NodeStateConflict(NodeRegistryError):
    """Raised when a node lifecycle transition is not permitted."""


class NodeLifecycle(str, Enum):
    DISCOVERED = "discovered"
    REACHABLE = "reachable"
    CAPABILITY_PROBED = "capability_probed"
    IDENTITY_VERIFIED = "identity_verified"
    AUTHENTICATED = "authenticated"
    PREPARED = "prepared"
    READY = "ready"
    ACTIVE = "active"
    DRAINING = "draining"
    QUARANTINED = "quarantined"
    FAILED = "failed"
    REVOKED = "revoked"


_TRANSITIONS: dict[NodeLifecycle, set[NodeLifecycle]] = {
    NodeLifecycle.DISCOVERED: {NodeLifecycle.REACHABLE, NodeLifecycle.QUARANTINED, NodeLifecycle.REVOKED},
    NodeLifecycle.REACHABLE: {NodeLifecycle.CAPABILITY_PROBED, NodeLifecycle.QUARANTINED, NodeLifecycle.FAILED, NodeLifecycle.REVOKED},
    NodeLifecycle.CAPABILITY_PROBED: {NodeLifecycle.IDENTITY_VERIFIED, NodeLifecycle.QUARANTINED, NodeLifecycle.REVOKED},
    NodeLifecycle.IDENTITY_VERIFIED: {NodeLifecycle.AUTHENTICATED, NodeLifecycle.QUARANTINED, NodeLifecycle.REVOKED},
    NodeLifecycle.AUTHENTICATED: {NodeLifecycle.PREPARED, NodeLifecycle.QUARANTINED, NodeLifecycle.REVOKED},
    NodeLifecycle.PREPARED: {NodeLifecycle.READY, NodeLifecycle.QUARANTINED, NodeLifecycle.REVOKED},
    NodeLifecycle.READY: {NodeLifecycle.ACTIVE, NodeLifecycle.DRAINING, NodeLifecycle.QUARANTINED, NodeLifecycle.REVOKED},
    NodeLifecycle.ACTIVE: {NodeLifecycle.DRAINING, NodeLifecycle.QUARANTINED, NodeLifecycle.REVOKED},
    NodeLifecycle.DRAINING: {NodeLifecycle.READY, NodeLifecycle.QUARANTINED, NodeLifecycle.REVOKED},
    NodeLifecycle.QUARANTINED: {NodeLifecycle.REACHABLE, NodeLifecycle.REVOKED},
    NodeLifecycle.FAILED: {NodeLifecycle.REACHABLE, NodeLifecycle.QUARANTINED, NodeLifecycle.REVOKED},
    NodeLifecycle.REVOKED: set(),
}
_IDENTIFIER = re.compile(r"^[A-Za-z0-9_.:-]{1,160}$")


@dataclass(frozen=True)
class NodeRecord:
    node_id: str
    endpoint: str
    discovery_source: str
    status: NodeLifecycle
    principal_id: str
    identity_key_id: str
    capabilities: tuple[str, ...]
    models: tuple[Mapping[str, Any], ...]
    profile_revision: int | None
    benchmark: Mapping[str, Any]
    auth_required: bool
    reason: str
    version: int
    first_seen: float
    last_seen: float
    updated_at: float

    def to_dict(self) -> dict[str, Any]:
        return {
            "node_id": self.node_id,
            "endpoint": self.endpoint,
            "discovery_source": self.discovery_source,
            "status": self.status.value,
            "principal_id": self.principal_id,
            "identity_key_id": self.identity_key_id,
            "capabilities": list(self.capabilities),
            "models": [dict(model) for model in self.models],
            "profile_revision": self.profile_revision,
            "benchmark": dict(self.benchmark),
            "auth_required": self.auth_required,
            "reason": self.reason,
            "version": self.version,
            "first_seen": self.first_seen,
            "last_seen": self.last_seen,
            "updated_at": self.updated_at,
        }


@dataclass(frozen=True)
class NodeRegistryEvent:
    event_id: str
    node_id: str
    event_type: str
    payload: Mapping[str, Any]
    created_at: float


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)


class NodeRegistry:
    """SQLite-backed node inventory with fail-closed lifecycle transitions."""

    def __init__(self, path: str | Path = ":memory:") -> None:
        self.path = Path(path)
        if str(path) != ":memory:":
            self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._connection = sqlite3.connect(str(path), check_same_thread=False, timeout=30.0)
        self._connection.row_factory = sqlite3.Row
        self._connection.execute("PRAGMA foreign_keys = ON")
        self._connection.execute("PRAGMA busy_timeout = 30000")
        if str(path) != ":memory:":
            self._connection.execute("PRAGMA journal_mode = WAL")
        self._connection.execute("PRAGMA synchronous = NORMAL")
        self._create_schema()

    def _create_schema(self) -> None:
        with self._transaction() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS mesh_nodes (
                    node_id TEXT PRIMARY KEY,
                    endpoint TEXT NOT NULL,
                    discovery_source TEXT NOT NULL,
                    status TEXT NOT NULL,
                    principal_id TEXT NOT NULL DEFAULT '',
                    identity_key_id TEXT NOT NULL DEFAULT '',
                    capabilities_json TEXT NOT NULL,
                    models_json TEXT NOT NULL,
                    profile_revision INTEGER,
                    benchmark_json TEXT NOT NULL,
                    auth_required INTEGER NOT NULL DEFAULT 0,
                    reason TEXT NOT NULL DEFAULT '',
                    version INTEGER NOT NULL DEFAULT 1,
                    first_seen REAL NOT NULL,
                    last_seen REAL NOT NULL,
                    updated_at REAL NOT NULL
                );
                CREATE TABLE IF NOT EXISTS mesh_node_events (
                    event_id TEXT PRIMARY KEY,
                    node_id TEXT NOT NULL REFERENCES mesh_nodes(node_id) ON DELETE CASCADE,
                    event_type TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    created_at REAL NOT NULL
                );
                CREATE INDEX IF NOT EXISTS mesh_nodes_status_idx ON mesh_nodes(status, last_seen);
                CREATE INDEX IF NOT EXISTS mesh_node_events_idx ON mesh_node_events(node_id, created_at);
                """
            )

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
    def _record(row: sqlite3.Row) -> NodeRecord:
        return NodeRecord(
            node_id=str(row["node_id"]),
            endpoint=str(row["endpoint"]),
            discovery_source=str(row["discovery_source"]),
            status=NodeLifecycle(str(row["status"])),
            principal_id=str(row["principal_id"]),
            identity_key_id=str(row["identity_key_id"]),
            capabilities=tuple(json.loads(str(row["capabilities_json"]))),
            models=tuple(json.loads(str(row["models_json"]))),
            profile_revision=(int(row["profile_revision"]) if row["profile_revision"] is not None else None),
            benchmark=json.loads(str(row["benchmark_json"])),
            auth_required=bool(row["auth_required"]),
            reason=str(row["reason"]),
            version=int(row["version"]),
            first_seen=float(row["first_seen"]),
            last_seen=float(row["last_seen"]),
            updated_at=float(row["updated_at"]),
        )

    def _require(self, connection: sqlite3.Connection, node_id: str) -> sqlite3.Row:
        row = connection.execute("SELECT * FROM mesh_nodes WHERE node_id = ?", (node_id,)).fetchone()
        if row is None:
            raise KeyError(f"unknown mesh node: {node_id}")
        return row

    def _event(self, connection: sqlite3.Connection, node_id: str, event_type: str, payload: Mapping[str, Any]) -> None:
        connection.execute(
            "INSERT INTO mesh_node_events (event_id, node_id, event_type, payload_json, created_at) VALUES (?, ?, ?, ?, ?)",
            (f"nodeevt_{uuid.uuid4().hex}", node_id, event_type, _json(dict(payload)), time.time()),
        )

    @staticmethod
    def _validate_node(node_id: str, endpoint: str, discovery_source: str) -> None:
        if not _IDENTIFIER.fullmatch(str(node_id)):
            raise ValueError("invalid node_id")
        if not 1 <= len(str(endpoint)) <= 512:
            raise ValueError("endpoint must be 1..512 characters")
        if not 1 <= len(str(discovery_source)) <= 128:
            raise ValueError("discovery_source must be 1..128 characters")

    def discover(self, node_id: str, endpoint: str, *, discovery_source: str = "lan") -> NodeRecord:
        self._validate_node(node_id, endpoint, discovery_source)
        timestamp = time.time()
        with self._transaction() as connection:
            prior = connection.execute("SELECT * FROM mesh_nodes WHERE node_id = ?", (node_id,)).fetchone()
            if prior is None:
                connection.execute(
                    """INSERT INTO mesh_nodes
                       (node_id, endpoint, discovery_source, status, capabilities_json,
                        models_json, benchmark_json, first_seen, last_seen, updated_at)
                       VALUES (?, ?, ?, ?, '[]', '[]', '{}', ?, ?, ?)""",
                    (node_id, endpoint, discovery_source, NodeLifecycle.DISCOVERED.value, timestamp, timestamp, timestamp),
                )
                self._event(connection, node_id, "node.discovered", {"source": discovery_source})
            else:
                if NodeLifecycle(str(prior["status"])) is not NodeLifecycle.REVOKED:
                    connection.execute(
                        "UPDATE mesh_nodes SET endpoint = ?, discovery_source = ?, last_seen = ?, updated_at = ?, version = version + 1 WHERE node_id = ?",
                        (endpoint, discovery_source, timestamp, timestamp, node_id),
                    )
                    self._event(connection, node_id, "node.seen", {"source": discovery_source})
            return self._record(self._require(connection, node_id))

    def get(self, node_id: str) -> NodeRecord:
        with self._lock:
            row = self._require(self._connection, str(node_id))
            return self._record(row)

    def _transition(self, connection: sqlite3.Connection, node_id: str, target: NodeLifecycle, *, reason: str = "") -> NodeRecord:
        row = self._require(connection, node_id)
        current = NodeLifecycle(str(row["status"]))
        if target is not current and target not in _TRANSITIONS[current]:
            raise NodeStateConflict(f"invalid node transition: {current.value} -> {target.value}")
        timestamp = time.time()
        connection.execute(
            "UPDATE mesh_nodes SET status = ?, reason = ?, version = version + 1, updated_at = ? WHERE node_id = ?",
            (target.value, str(reason)[:512], timestamp, node_id),
        )
        self._event(connection, node_id, "node.status_changed", {"from": current.value, "to": target.value, "reason": str(reason)[:512]})
        return self._record(self._require(connection, node_id))

    def mark_reachable(self, node_id: str) -> NodeRecord:
        with self._transaction() as connection:
            return self._transition(connection, str(node_id), NodeLifecycle.REACHABLE)

    def record_capabilities(
        self,
        node_id: str,
        *,
        capabilities: Sequence[str],
        models: Sequence[Mapping[str, Any]],
        profile_revision: int,
    ) -> NodeRecord:
        if not 0 <= int(profile_revision) <= 2**63 - 1:
            raise ValueError("profile_revision must be non-negative")
        clean_capabilities = tuple(sorted({str(value) for value in capabilities if str(value)}))
        if len(clean_capabilities) > 256 or any(len(value) > 128 for value in clean_capabilities):
            raise ValueError("capabilities are bounded")
        if len(models) > 512:
            raise ValueError("models are bounded")
        clean_models = tuple(dict(model) for model in models)
        with self._transaction() as connection:
            row = self._require(connection, str(node_id))
            current = NodeLifecycle(str(row["status"]))
            if current is not NodeLifecycle.REACHABLE:
                raise NodeStateConflict(f"capability probe is not allowed in state {current.value}")
            timestamp = time.time()
            connection.execute(
                "UPDATE mesh_nodes SET capabilities_json = ?, models_json = ?, profile_revision = ?, last_seen = ?, version = version + 1, updated_at = ? WHERE node_id = ?",
                (_json(clean_capabilities), _json(clean_models), int(profile_revision), timestamp, timestamp, str(node_id)),
            )
            self._event(connection, str(node_id), "node.capabilities_probed", {"capability_count": len(clean_capabilities), "model_count": len(clean_models), "profile_revision": int(profile_revision)})
            return self._transition(connection, str(node_id), NodeLifecycle.CAPABILITY_PROBED)

    def refresh_verified_capabilities(
        self,
        node_id: str,
        *,
        capabilities: Sequence[str],
        models: Sequence[Mapping[str, Any]],
        profile_revision: int,
    ) -> NodeRecord:
        """Refresh an already authenticated inventory without weakening trust state."""
        if not 0 <= int(profile_revision) <= 2**63 - 1:
            raise ValueError("profile_revision must be non-negative")
        clean_capabilities = tuple(sorted({str(value) for value in capabilities if str(value)}))
        if len(clean_capabilities) > 256 or any(len(value) > 128 for value in clean_capabilities):
            raise ValueError("capabilities are bounded")
        if len(models) > 512:
            raise ValueError("models are bounded")
        clean_models = tuple(dict(model) for model in models)
        allowed = {
            NodeLifecycle.CAPABILITY_PROBED,
            NodeLifecycle.IDENTITY_VERIFIED,
            NodeLifecycle.AUTHENTICATED,
            NodeLifecycle.PREPARED,
            NodeLifecycle.READY,
            NodeLifecycle.ACTIVE,
        }
        with self._transaction() as connection:
            row = self._require(connection, str(node_id))
            current = NodeLifecycle(str(row["status"]))
            if current not in allowed:
                raise NodeStateConflict(f"verified capability refresh is not allowed in state {current.value}")
            prior_revision = row["profile_revision"]
            if prior_revision is not None and int(profile_revision) < int(prior_revision):
                raise NodeStateConflict("profile revision moved backwards")
            timestamp = time.time()
            connection.execute(
                "UPDATE mesh_nodes SET capabilities_json = ?, models_json = ?, profile_revision = ?, last_seen = ?, version = version + 1, updated_at = ? WHERE node_id = ?",
                (_json(clean_capabilities), _json(clean_models), int(profile_revision), timestamp, timestamp, str(node_id)),
            )
            self._event(connection, str(node_id), "node.capabilities_refreshed", {"capability_count": len(clean_capabilities), "model_count": len(clean_models), "profile_revision": int(profile_revision)})
            return self._record(self._require(connection, str(node_id)))

    def verify_identity(self, node_id: str, *, identity_key_id: str, evidence_digest: str) -> NodeRecord:
        if not _IDENTIFIER.fullmatch(str(identity_key_id)) or not re.fullmatch(r"[A-Fa-f0-9]{64}", str(evidence_digest)):
            raise ValueError("identity evidence must contain a key id and sha256 digest")
        with self._transaction() as connection:
            row = self._require(connection, str(node_id))
            if NodeLifecycle(str(row["status"])) is not NodeLifecycle.CAPABILITY_PROBED:
                raise NodeStateConflict("identity verification requires a completed capability probe")
            connection.execute(
                "UPDATE mesh_nodes SET identity_key_id = ?, version = version + 1, updated_at = ? WHERE node_id = ?",
                (str(identity_key_id), time.time(), str(node_id)),
            )
            self._event(connection, str(node_id), "node.identity_verified", {"identity_key_id": str(identity_key_id), "evidence_digest": str(evidence_digest)})
            return self._transition(connection, str(node_id), NodeLifecycle.IDENTITY_VERIFIED)

    def mark_authenticated(self, node_id: str, *, principal_id: str) -> NodeRecord:
        if not _IDENTIFIER.fullmatch(str(principal_id)):
            raise ValueError("invalid principal_id")
        with self._transaction() as connection:
            row = self._require(connection, str(node_id))
            if NodeLifecycle(str(row["status"])) is not NodeLifecycle.IDENTITY_VERIFIED:
                raise NodeStateConflict("authentication requires verified identity")
            connection.execute(
                "UPDATE mesh_nodes SET principal_id = ?, auth_required = 0, version = version + 1, updated_at = ? WHERE node_id = ?",
                (str(principal_id), time.time(), str(node_id)),
            )
            return self._transition(connection, str(node_id), NodeLifecycle.AUTHENTICATED)

    def mark_prepared(self, node_id: str, *, preparation_digest: str) -> NodeRecord:
        if not re.fullmatch(r"[A-Fa-f0-9]{64}", str(preparation_digest)):
            raise ValueError("preparation_digest must be a sha256 digest")
        with self._transaction() as connection:
            row = self._require(connection, str(node_id))
            if NodeLifecycle(str(row["status"])) is not NodeLifecycle.AUTHENTICATED:
                raise NodeStateConflict("preparation requires authentication")
            connection.execute("UPDATE mesh_nodes SET reason = ?, version = version + 1, updated_at = ? WHERE node_id = ?", (f"prepared:{preparation_digest}", time.time(), str(node_id)))
            return self._transition(connection, str(node_id), NodeLifecycle.PREPARED)

    def record_benchmark(self, node_id: str, *, accepted: bool, metrics: Mapping[str, Any]) -> NodeRecord:
        if len(metrics) > 128:
            raise ValueError("benchmark metrics are bounded")
        with self._transaction() as connection:
            row = self._require(connection, str(node_id))
            current = NodeLifecycle(str(row["status"]))
            if current is not NodeLifecycle.PREPARED:
                raise NodeStateConflict(f"benchmark is not allowed in state {current.value}")
            target = NodeLifecycle.READY if accepted else NodeLifecycle.QUARANTINED
            connection.execute("UPDATE mesh_nodes SET benchmark_json = ?, version = version + 1, updated_at = ? WHERE node_id = ?", (_json(dict(metrics)), time.time(), str(node_id)))
            self._event(connection, str(node_id), "node.benchmark_accepted" if accepted else "node.benchmark_rejected", {"accepted": bool(accepted)})
            return self._transition(connection, str(node_id), target, reason="benchmark_accepted" if accepted else "benchmark_rejected")

    def mark_authentication_required(self, node_id: str, *, reason: str = "manual_pairing_required") -> NodeRecord:
        with self._transaction() as connection:
            row = self._require(connection, str(node_id))
            if NodeLifecycle(str(row["status"])) is NodeLifecycle.REVOKED:
                return self._record(row)
            connection.execute("UPDATE mesh_nodes SET auth_required = 1, reason = ?, version = version + 1, updated_at = ? WHERE node_id = ?", (str(reason)[:512], time.time(), str(node_id)))
            return self._transition(connection, str(node_id), NodeLifecycle.QUARANTINED, reason=str(reason))

    def quarantine(self, node_id: str, *, reason: str) -> NodeRecord:
        with self._transaction() as connection:
            return self._transition(connection, str(node_id), NodeLifecycle.QUARANTINED, reason=reason)

    def activate(self, node_id: str) -> NodeRecord:
        with self._transaction() as connection:
            return self._transition(connection, str(node_id), NodeLifecycle.ACTIVE, reason="scheduler_activated")

    def drain(self, node_id: str, *, reason: str = "drain") -> NodeRecord:
        with self._transaction() as connection:
            return self._transition(connection, str(node_id), NodeLifecycle.DRAINING, reason=reason)

    def revoke(self, node_id: str, *, reason: str = "revoked") -> NodeRecord:
        with self._transaction() as connection:
            return self._transition(connection, str(node_id), NodeLifecycle.REVOKED, reason=reason)

    def list_visible(self) -> tuple[NodeRecord, ...]:
        with self._lock:
            rows = self._connection.execute("SELECT * FROM mesh_nodes WHERE status != ? ORDER BY node_id", (NodeLifecycle.REVOKED.value,)).fetchall()
        return tuple(self._record(row) for row in rows)

    def routable_nodes(self) -> tuple[NodeRecord, ...]:
        with self._lock:
            rows = self._connection.execute(
                "SELECT * FROM mesh_nodes WHERE status IN (?, ?) AND auth_required = 0 AND identity_key_id != '' AND principal_id != '' ORDER BY node_id",
                (NodeLifecycle.READY.value, NodeLifecycle.ACTIVE.value),
            ).fetchall()
        return tuple(self._record(row) for row in rows)

    def reconcile_stale_nodes(
        self,
        max_age_seconds: float,
        *,
        now: float | None = None,
    ) -> tuple[NodeRecord, ...]:
        """Quarantine routable nodes whose authenticated visibility has expired.

        Staleness is deliberately fail-closed: a node is removed from routing
        before it can be used again, and a later authenticated profile/session
        sync must move it through the normal admission path. Discovery alone
        cannot restore a quarantined node.
        """
        age_limit = float(max_age_seconds)
        if age_limit <= 0:
            raise ValueError("max_age_seconds must be positive")
        current_time = time.time() if now is None else float(now)
        with self._transaction() as connection:
            rows = connection.execute(
                "SELECT node_id, last_seen FROM mesh_nodes WHERE status IN (?, ?)",
                (NodeLifecycle.READY.value, NodeLifecycle.ACTIVE.value),
            ).fetchall()
            stale: list[NodeRecord] = []
            for row in rows:
                age = current_time - float(row["last_seen"])
                if age <= age_limit:
                    continue
                reason = f"heartbeat_stale:{min(age, 9_999_999_999.0):.3f}s"
                stale.append(self._transition(connection, str(row["node_id"]), NodeLifecycle.QUARANTINED, reason=reason))
            return tuple(stale)

    def list_events(self, node_id: str, *, limit: int = 100) -> tuple[NodeRegistryEvent, ...]:
        with self._lock:
            rows = self._connection.execute("SELECT * FROM mesh_node_events WHERE node_id = ? ORDER BY created_at LIMIT ?", (str(node_id), max(1, min(int(limit), 1000)))).fetchall()
        return tuple(NodeRegistryEvent(str(row["event_id"]), str(row["node_id"]), str(row["event_type"]), json.loads(str(row["payload_json"])), float(row["created_at"])) for row in rows)

    def close(self) -> None:
        with self._lock:
            self._connection.close()

    def __enter__(self) -> "NodeRegistry":
        return self

    def __exit__(self, *exc: Any) -> None:
        self.close()
