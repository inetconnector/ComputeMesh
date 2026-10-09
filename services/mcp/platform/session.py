"""Durable, dependency-light Agent session, turn and event contracts.

The store is deliberately independent from model providers, MCP transports and
private placement policy. It provides the durable lifecycle boundary that those
systems can attach to without changing the legacy chat path.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import math
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


class SessionStateConflict(RuntimeError):
    """Raised when a durable session or turn transition is not valid."""


class SessionStatus(str, Enum):
    CREATING = "creating"
    READY = "ready"
    RUNNING = "running"
    WAITING_FOR_TOOL = "waiting_for_tool"
    WAITING_FOR_APPROVAL = "waiting_for_approval"
    WAITING_FOR_SUBAGENTS = "waiting_for_subagents"
    COMPACTING = "compacting"
    PAUSED = "paused"
    RESUMING = "resuming"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"
    EXPIRED = "expired"


class TurnStatus(str, Enum):
    QUEUED = "queued"
    RUNNING = "running"
    WAITING_FOR_TOOL = "waiting_for_tool"
    WAITING_FOR_APPROVAL = "waiting_for_approval"
    WAITING_FOR_SUBAGENTS = "waiting_for_subagents"
    COMPACTING = "compacting"
    PAUSED = "paused"
    RESUMING = "resuming"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class ApprovalStatus(str, Enum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    EXPIRED = "expired"
    CONSUMED = "consumed"


class ControlAction(str, Enum):
    PAUSE = "pause"
    RESUME = "resume"
    CANCEL = "cancel"


class ControlStatus(str, Enum):
    REQUESTED = "requested"
    APPLIED = "applied"
    REJECTED = "rejected"


_ACTIVE_TURN_STATUSES = {
    TurnStatus.QUEUED,
    TurnStatus.RUNNING,
    TurnStatus.WAITING_FOR_TOOL,
    TurnStatus.WAITING_FOR_APPROVAL,
    TurnStatus.WAITING_FOR_SUBAGENTS,
    TurnStatus.COMPACTING,
    TurnStatus.RESUMING,
}

_SESSION_TRANSITIONS: dict[SessionStatus, set[SessionStatus]] = {
    SessionStatus.CREATING: {SessionStatus.READY, SessionStatus.FAILED, SessionStatus.CANCELLED},
    SessionStatus.READY: {SessionStatus.RUNNING, SessionStatus.COMPLETED, SessionStatus.PAUSED, SessionStatus.CANCELLED, SessionStatus.EXPIRED},
    SessionStatus.RUNNING: {
        SessionStatus.WAITING_FOR_TOOL,
        SessionStatus.WAITING_FOR_APPROVAL,
        SessionStatus.WAITING_FOR_SUBAGENTS,
        SessionStatus.COMPACTING,
        SessionStatus.PAUSED,
        SessionStatus.READY,
        SessionStatus.FAILED,
        SessionStatus.CANCELLED,
    },
    SessionStatus.WAITING_FOR_TOOL: {SessionStatus.RUNNING, SessionStatus.READY, SessionStatus.PAUSED, SessionStatus.FAILED, SessionStatus.CANCELLED},
    SessionStatus.WAITING_FOR_APPROVAL: {SessionStatus.RUNNING, SessionStatus.READY, SessionStatus.PAUSED, SessionStatus.FAILED, SessionStatus.CANCELLED},
    SessionStatus.WAITING_FOR_SUBAGENTS: {SessionStatus.RUNNING, SessionStatus.READY, SessionStatus.PAUSED, SessionStatus.FAILED, SessionStatus.CANCELLED},
    SessionStatus.COMPACTING: {SessionStatus.RUNNING, SessionStatus.PAUSED, SessionStatus.FAILED},
    SessionStatus.PAUSED: {SessionStatus.RESUMING, SessionStatus.CANCELLED, SessionStatus.EXPIRED},
    SessionStatus.RESUMING: {SessionStatus.READY, SessionStatus.RUNNING, SessionStatus.FAILED},
    SessionStatus.FAILED: {SessionStatus.RESUMING, SessionStatus.CANCELLED, SessionStatus.EXPIRED},
    SessionStatus.COMPLETED: set(),
    SessionStatus.CANCELLED: set(),
    SessionStatus.EXPIRED: set(),
}

_TURN_TRANSITIONS: dict[TurnStatus, set[TurnStatus]] = {
    TurnStatus.QUEUED: {TurnStatus.RUNNING, TurnStatus.PAUSED, TurnStatus.CANCELLED, TurnStatus.FAILED},
    TurnStatus.RUNNING: {
        TurnStatus.WAITING_FOR_TOOL,
        TurnStatus.WAITING_FOR_APPROVAL,
        TurnStatus.WAITING_FOR_SUBAGENTS,
        TurnStatus.COMPACTING,
        TurnStatus.PAUSED,
        TurnStatus.COMPLETED,
        TurnStatus.FAILED,
        TurnStatus.CANCELLED,
    },
    TurnStatus.WAITING_FOR_TOOL: {TurnStatus.RUNNING, TurnStatus.PAUSED, TurnStatus.FAILED, TurnStatus.CANCELLED},
    TurnStatus.WAITING_FOR_APPROVAL: {TurnStatus.RUNNING, TurnStatus.RESUMING, TurnStatus.PAUSED, TurnStatus.FAILED, TurnStatus.CANCELLED},
    TurnStatus.WAITING_FOR_SUBAGENTS: {TurnStatus.RUNNING, TurnStatus.PAUSED, TurnStatus.FAILED, TurnStatus.CANCELLED},
    TurnStatus.COMPACTING: {TurnStatus.RUNNING, TurnStatus.PAUSED, TurnStatus.FAILED},
    TurnStatus.PAUSED: {TurnStatus.RESUMING, TurnStatus.CANCELLED, TurnStatus.FAILED},
    TurnStatus.RESUMING: {TurnStatus.RUNNING, TurnStatus.PAUSED, TurnStatus.FAILED},
    TurnStatus.COMPLETED: set(),
    TurnStatus.FAILED: {TurnStatus.RESUMING, TurnStatus.CANCELLED},
    TurnStatus.CANCELLED: set(),
}

_SECRET_KEY = re.compile(r"(token|secret|password|api[_-]?key|authorization|cookie|private[_-]?key)", re.I)
_MAX_TURN_CHECKPOINT_BYTES = 4 * 1024 * 1024


def _now() -> float:
    return time.time()


def _new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex}"


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)


def _redact(value: Any, *, max_string: int = 4096) -> Any:
    if isinstance(value, Mapping):
        return {
            str(key): "[REDACTED]" if _SECRET_KEY.search(str(key)) else _redact(item, max_string=max_string)
            for key, item in value.items()
        }
    if isinstance(value, (list, tuple)):
        return [_redact(item, max_string=max_string) for item in value]
    if isinstance(value, str) and len(value) > max_string:
        return value[:max_string] + "…[truncated]"
    return value


def _items(value: str | Mapping[str, Any] | Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    if isinstance(value, str):
        return [{"role": "user", "content": value}]
    if isinstance(value, Mapping):
        return [dict(value)]
    result = [dict(item) for item in value]
    if not result:
        raise ValueError("at least one session item is required")
    return result


@dataclass(frozen=True)
class AgentSession:
    session_id: str
    agent_id: str
    agent_version: str
    status: SessionStatus
    principal_id: str
    environment_type: str
    state: Mapping[str, Any]
    version: int
    created_at: float
    updated_at: float

    def to_dict(self) -> dict[str, Any]:
        return {
            "session_id": self.session_id,
            "agent_id": self.agent_id,
            "agent_version": self.agent_version,
            "status": self.status.value,
            "principal_id": self.principal_id,
            "environment_type": self.environment_type,
            "state": dict(self.state),
            "version": self.version,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }


@dataclass(frozen=True)
class AgentTurn:
    turn_id: str
    session_id: str
    status: TurnStatus
    version: int
    error: str
    created_at: float
    updated_at: float
    priority: int = 0
    deadline_at: float | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "turn_id": self.turn_id,
            "session_id": self.session_id,
            "status": self.status.value,
            "version": self.version,
            "error": self.error,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "priority": self.priority,
            "deadline_at": self.deadline_at,
        }


@dataclass(frozen=True)
class AgentItem:
    item_id: str
    session_id: str
    turn_id: str
    kind: str
    content: Mapping[str, Any]
    sequence: int
    created_at: float


@dataclass(frozen=True)
class SessionEvent:
    event_id: str
    session_id: str
    turn_id: str | None
    sequence: int
    event_type: str
    payload: Mapping[str, Any]
    created_at: float
    dispatched_at: float | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "event_id": self.event_id,
            "session_id": self.session_id,
            "turn_id": self.turn_id,
            "sequence": self.sequence,
            "event_type": self.event_type,
            "payload": dict(self.payload),
            "created_at": self.created_at,
            "dispatched_at": self.dispatched_at,
        }


@dataclass(frozen=True)
class EventPage:
    """Cursor page used by reconnecting clients such as Android/WebUI."""

    events: tuple[SessionEvent, ...]
    next_sequence: int
    has_more: bool

    def to_dict(self) -> dict[str, Any]:
        return {
            "events": [event.to_dict() for event in self.events],
            "next_sequence": self.next_sequence,
            "has_more": self.has_more,
        }


@dataclass(frozen=True)
class Approval:
    approval_id: str
    session_id: str
    turn_id: str | None
    tool_id: str
    call_id: str
    arguments_digest: str
    principal_id: str
    status: ApprovalStatus
    expires_at: float
    created_at: float
    resolved_at: float | None
    resolution_reason: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "approval_id": self.approval_id,
            "session_id": self.session_id,
            "turn_id": self.turn_id,
            "tool_id": self.tool_id,
            "call_id": self.call_id,
            "arguments_digest": self.arguments_digest,
            "principal_id": self.principal_id,
            "status": self.status.value,
            "expires_at": self.expires_at,
            "created_at": self.created_at,
            "resolved_at": self.resolved_at,
            "resolution_reason": self.resolution_reason,
        }


@dataclass(frozen=True)
class AgentControl:
    """Durable, principal-bound control request for a session turn."""

    control_id: str
    session_id: str
    turn_id: str | None
    action: ControlAction
    status: ControlStatus
    principal_id: str
    created_at: float
    resolved_at: float | None
    reason: str

    def to_dict(self) -> dict[str, Any]:
        # The principal is an authorization detail and is intentionally not
        # exposed through client projections.
        return {
            "control_id": self.control_id,
            "session_id": self.session_id,
            "turn_id": self.turn_id,
            "action": self.action.value,
            "status": self.status.value,
            "created_at": self.created_at,
            "resolved_at": self.resolved_at,
            "reason": self.reason,
        }


class AgentSessionStore:
    """SQLite-backed sessions with atomic transitions and an event outbox."""

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
                CREATE TABLE IF NOT EXISTS agent_sessions (
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
                CREATE TABLE IF NOT EXISTS agent_turns (
                    turn_id TEXT PRIMARY KEY,
                    session_id TEXT NOT NULL REFERENCES agent_sessions(session_id) ON DELETE CASCADE,
                    status TEXT NOT NULL,
                    version INTEGER NOT NULL DEFAULT 1,
                    error TEXT NOT NULL DEFAULT '',
                    created_at REAL NOT NULL,
                    updated_at REAL NOT NULL,
                    priority INTEGER NOT NULL DEFAULT 0,
                    deadline_at REAL,
                    checkpoint_json TEXT NOT NULL DEFAULT ''
                );
                CREATE INDEX IF NOT EXISTS agent_turns_session_idx
                    ON agent_turns(session_id, created_at);
                CREATE TABLE IF NOT EXISTS agent_items (
                    item_id TEXT PRIMARY KEY,
                    session_id TEXT NOT NULL REFERENCES agent_sessions(session_id) ON DELETE CASCADE,
                    turn_id TEXT NOT NULL REFERENCES agent_turns(turn_id) ON DELETE CASCADE,
                    kind TEXT NOT NULL,
                    content_json TEXT NOT NULL,
                    sequence INTEGER NOT NULL,
                    created_at REAL NOT NULL,
                    UNIQUE(session_id, sequence)
                );
                CREATE TABLE IF NOT EXISTS agent_events (
                    event_id TEXT PRIMARY KEY,
                    session_id TEXT NOT NULL REFERENCES agent_sessions(session_id) ON DELETE CASCADE,
                    turn_id TEXT REFERENCES agent_turns(turn_id) ON DELETE SET NULL,
                    sequence INTEGER NOT NULL,
                    event_type TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    created_at REAL NOT NULL,
                    dispatched_at REAL,
                    claimed_by TEXT,
                    claimed_at REAL,
                    claim_expires_at REAL,
                    outbox_attempts INTEGER NOT NULL DEFAULT 0,
                    UNIQUE(session_id, sequence)
                );
                CREATE INDEX IF NOT EXISTS agent_events_outbox_idx
                    ON agent_events(dispatched_at, created_at);
                CREATE TABLE IF NOT EXISTS agent_approvals (
                    approval_id TEXT PRIMARY KEY,
                    session_id TEXT NOT NULL REFERENCES agent_sessions(session_id) ON DELETE CASCADE,
                    turn_id TEXT REFERENCES agent_turns(turn_id) ON DELETE SET NULL,
                    tool_id TEXT NOT NULL,
                    call_id TEXT NOT NULL,
                    arguments_digest TEXT NOT NULL,
                    principal_id TEXT NOT NULL,
                    status TEXT NOT NULL,
                    expires_at REAL NOT NULL,
                    created_at REAL NOT NULL,
                    resolved_at REAL,
                    resolution_reason TEXT NOT NULL DEFAULT ''
                );
                CREATE INDEX IF NOT EXISTS agent_approvals_session_idx
                    ON agent_approvals(session_id, created_at);
                CREATE INDEX IF NOT EXISTS agent_approvals_principal_idx
                    ON agent_approvals(principal_id, status, expires_at);
                CREATE TABLE IF NOT EXISTS agent_controls (
                    control_id TEXT PRIMARY KEY,
                    session_id TEXT NOT NULL REFERENCES agent_sessions(session_id) ON DELETE CASCADE,
                    turn_id TEXT REFERENCES agent_turns(turn_id) ON DELETE SET NULL,
                    action TEXT NOT NULL,
                    status TEXT NOT NULL,
                    principal_id TEXT NOT NULL,
                    created_at REAL NOT NULL,
                    resolved_at REAL,
                    reason TEXT NOT NULL DEFAULT ''
                );
                CREATE INDEX IF NOT EXISTS agent_controls_pending_idx
                    ON agent_controls(session_id, turn_id, status, created_at);
                """
            )
            # Keep existing operator databases compatible with the durable
            # scheduling fields introduced after the initial session schema.
            columns = {
                str(row["name"])
                for row in connection.execute("PRAGMA table_info(agent_turns)").fetchall()
            }
            if "priority" not in columns:
                connection.execute(
                    "ALTER TABLE agent_turns ADD COLUMN priority INTEGER NOT NULL DEFAULT 0"
                )
            if "deadline_at" not in columns:
                connection.execute("ALTER TABLE agent_turns ADD COLUMN deadline_at REAL")
            if "checkpoint_json" not in columns:
                connection.execute(
                    "ALTER TABLE agent_turns ADD COLUMN checkpoint_json TEXT NOT NULL DEFAULT ''"
                )
            event_columns = {
                str(row["name"])
                for row in connection.execute("PRAGMA table_info(agent_events)").fetchall()
            }
            if "claimed_by" not in event_columns:
                connection.execute("ALTER TABLE agent_events ADD COLUMN claimed_by TEXT")
            if "claimed_at" not in event_columns:
                connection.execute("ALTER TABLE agent_events ADD COLUMN claimed_at REAL")
            if "claim_expires_at" not in event_columns:
                connection.execute("ALTER TABLE agent_events ADD COLUMN claim_expires_at REAL")
            if "outbox_attempts" not in event_columns:
                connection.execute(
                    "ALTER TABLE agent_events ADD COLUMN outbox_attempts INTEGER NOT NULL DEFAULT 0"
                )
            connection.execute(
                """CREATE INDEX IF NOT EXISTS agent_turns_scheduler_idx
                   ON agent_turns(status, priority, deadline_at, created_at)"""
            )
            connection.execute(
                """CREATE INDEX IF NOT EXISTS agent_events_outbox_claim_idx
                   ON agent_events(dispatched_at, claimed_at, created_at)"""
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
    def _session(row: sqlite3.Row) -> AgentSession:
        return AgentSession(
            session_id=str(row["session_id"]),
            agent_id=str(row["agent_id"]),
            agent_version=str(row["agent_version"]),
            status=SessionStatus(str(row["status"])),
            principal_id=str(row["principal_id"]),
            environment_type=str(row["environment_type"]),
            state=json.loads(str(row["state_json"])),
            version=int(row["version"]),
            created_at=float(row["created_at"]),
            updated_at=float(row["updated_at"]),
        )

    @staticmethod
    def _turn(row: sqlite3.Row) -> AgentTurn:
        return AgentTurn(
            turn_id=str(row["turn_id"]),
            session_id=str(row["session_id"]),
            status=TurnStatus(str(row["status"])),
            version=int(row["version"]),
            error=str(row["error"]),
            created_at=float(row["created_at"]),
            updated_at=float(row["updated_at"]),
            priority=int(row["priority"]),
            deadline_at=(float(row["deadline_at"]) if row["deadline_at"] is not None else None),
        )

    @staticmethod
    def _validate_turn_schedule(priority: int, deadline_at: float | None) -> tuple[int, float | None]:
        if isinstance(priority, bool):
            raise ValueError("priority must be an integer")
        try:
            clean_priority = int(priority)
        except (TypeError, ValueError) as exc:
            raise ValueError("priority must be an integer") from exc
        if not -1_000 <= clean_priority <= 1_000:
            raise ValueError("priority must be between -1000 and 1000")
        if deadline_at is None:
            return clean_priority, None
        try:
            clean_deadline = float(deadline_at)
        except (TypeError, ValueError) as exc:
            raise ValueError("deadline_at must be a finite Unix timestamp") from exc
        if not math.isfinite(clean_deadline) or clean_deadline <= 0:
            raise ValueError("deadline_at must be a positive finite Unix timestamp")
        return clean_priority, clean_deadline

    @staticmethod
    def _validate_routing_requirements(
        model_id: str,
        value: Mapping[str, Any] | None,
    ) -> dict[str, Any]:
        """Keep task routing to the minimized public requirement contract."""
        if value is None:
            return {}
        if not isinstance(value, Mapping):
            raise ValueError("routing must be an object")
        allowed = {
            "required_capabilities",
            "min_free_vram_bytes",
            "min_context_tokens",
            "min_decode_tokens_per_second",
            "max_latency_ms",
            "allowed_node_ids",
            "excluded_node_ids",
            "preferred_node_ids",
        }
        unknown = set(value) - allowed
        if unknown:
            raise ValueError("routing contains unsupported fields")

        def bounded_strings(name: str, *, maximum: int, item_maximum: int) -> list[str]:
            raw = value.get(name, ())
            if isinstance(raw, str) or not isinstance(raw, (list, tuple, set, frozenset)):
                raise ValueError(f"routing.{name} must be an array")
            result: list[str] = []
            for item in raw:
                clean = str(item).strip()
                if not 1 <= len(clean) <= item_maximum:
                    raise ValueError(f"routing.{name} contains an invalid value")
                if clean not in result:
                    result.append(clean)
            if len(result) > maximum:
                raise ValueError(f"routing.{name} is too large")
            return result

        def nonnegative_int(name: str, maximum: int) -> int | None:
            raw = value.get(name)
            if raw is None:
                return None
            if isinstance(raw, bool):
                raise ValueError(f"routing.{name} must be an integer")
            try:
                clean = int(raw)
            except (TypeError, ValueError) as exc:
                raise ValueError(f"routing.{name} must be an integer") from exc
            if clean < 0 or clean > maximum:
                raise ValueError(f"routing.{name} is outside the supported range")
            return clean

        result: dict[str, Any] = {}
        capabilities = bounded_strings("required_capabilities", maximum=128, item_maximum=128)
        if capabilities:
            result["required_capabilities"] = capabilities
        for name, maximum in (
            ("min_free_vram_bytes", 1 << 50),
            ("min_context_tokens", 1_000_000_000),
        ):
            clean = nonnegative_int(name, maximum)
            if clean is not None:
                result[name] = clean
        raw_tps = value.get("min_decode_tokens_per_second")
        if raw_tps is not None:
            try:
                clean_tps = float(raw_tps)
            except (TypeError, ValueError) as exc:
                raise ValueError("routing.min_decode_tokens_per_second must be numeric") from exc
            if not math.isfinite(clean_tps) or clean_tps < 0 or clean_tps > 1_000_000:
                raise ValueError("routing.min_decode_tokens_per_second is outside the supported range")
            result["min_decode_tokens_per_second"] = clean_tps
        raw_latency = value.get("max_latency_ms")
        if raw_latency is not None:
            try:
                clean_latency = float(raw_latency)
            except (TypeError, ValueError) as exc:
                raise ValueError("routing.max_latency_ms must be numeric") from exc
            if not math.isfinite(clean_latency) or clean_latency <= 0 or clean_latency > 86_400_000:
                raise ValueError("routing.max_latency_ms is outside the supported range")
            result["max_latency_ms"] = clean_latency
        for name in ("allowed_node_ids", "excluded_node_ids", "preferred_node_ids"):
            values = bounded_strings(name, maximum=1024, item_maximum=160)
            if values:
                result[name] = values
        return result

    @staticmethod
    def _validate_tenant_id(tenant_id: str | None) -> str:
        clean_tenant = str(tenant_id or "").strip()
        if len(clean_tenant) > 160:
            raise ValueError("tenant_id must be at most 160 characters")
        return clean_tenant

    @staticmethod
    def _event(row: sqlite3.Row) -> SessionEvent:
        return SessionEvent(
            event_id=str(row["event_id"]),
            session_id=str(row["session_id"]),
            turn_id=str(row["turn_id"]) if row["turn_id"] is not None else None,
            sequence=int(row["sequence"]),
            event_type=str(row["event_type"]),
            payload=json.loads(str(row["payload_json"])),
            created_at=float(row["created_at"]),
            dispatched_at=(float(row["dispatched_at"]) if row["dispatched_at"] is not None else None),
        )

    @staticmethod
    def _approval(row: sqlite3.Row) -> Approval:
        return Approval(
            approval_id=str(row["approval_id"]),
            session_id=str(row["session_id"]),
            turn_id=str(row["turn_id"]) if row["turn_id"] is not None else None,
            tool_id=str(row["tool_id"]),
            call_id=str(row["call_id"]),
            arguments_digest=str(row["arguments_digest"]),
            principal_id=str(row["principal_id"]),
            status=ApprovalStatus(str(row["status"])),
            expires_at=float(row["expires_at"]),
            created_at=float(row["created_at"]),
            resolved_at=float(row["resolved_at"]) if row["resolved_at"] is not None else None,
            resolution_reason=str(row["resolution_reason"]),
        )

    @staticmethod
    def _control(row: sqlite3.Row) -> AgentControl:
        return AgentControl(
            control_id=str(row["control_id"]),
            session_id=str(row["session_id"]),
            turn_id=str(row["turn_id"]) if row["turn_id"] is not None else None,
            action=ControlAction(str(row["action"])),
            status=ControlStatus(str(row["status"])),
            principal_id=str(row["principal_id"]),
            created_at=float(row["created_at"]),
            resolved_at=float(row["resolved_at"]) if row["resolved_at"] is not None else None,
            reason=str(row["reason"]),
        )

    def _require_session(self, connection: sqlite3.Connection, session_id: str) -> sqlite3.Row:
        row = connection.execute(
            "SELECT * FROM agent_sessions WHERE session_id = ?", (session_id,)
        ).fetchone()
        if row is None:
            raise KeyError(f"unknown agent session: {session_id}")
        return row

    def _require_turn(self, connection: sqlite3.Connection, turn_id: str) -> sqlite3.Row:
        row = connection.execute(
            "SELECT * FROM agent_turns WHERE turn_id = ?", (turn_id,)
        ).fetchone()
        if row is None:
            raise KeyError(f"unknown agent turn: {turn_id}")
        return row

    def _append_event(
        self,
        connection: sqlite3.Connection,
        session_id: str,
        event_type: str,
        payload: Mapping[str, Any] | None = None,
        *,
        turn_id: str | None = None,
    ) -> SessionEvent:
        created_at = _now()
        sequence = int(
            connection.execute(
                "SELECT COALESCE(MAX(sequence), 0) + 1 FROM agent_events WHERE session_id = ?",
                (session_id,),
            ).fetchone()[0]
        )
        event_id = _new_id("evt")
        connection.execute(
            """INSERT INTO agent_events
               (event_id, session_id, turn_id, sequence, event_type, payload_json, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (event_id, session_id, turn_id, sequence, str(event_type), _json(_redact(dict(payload or {}))), created_at),
        )
        row = connection.execute("SELECT * FROM agent_events WHERE event_id = ?", (event_id,)).fetchone()
        assert row is not None
        return self._event(row)

    def _append_item(
        self,
        connection: sqlite3.Connection,
        session_id: str,
        turn_id: str,
        kind: str,
        content: Mapping[str, Any],
    ) -> AgentItem:
        created_at = _now()
        sequence = int(
            connection.execute(
                "SELECT COALESCE(MAX(sequence), 0) + 1 FROM agent_items WHERE session_id = ?",
                (session_id,),
            ).fetchone()[0]
        )
        item_id = _new_id("item")
        connection.execute(
            """INSERT INTO agent_items
               (item_id, session_id, turn_id, kind, content_json, sequence, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (item_id, session_id, turn_id, str(kind), _json(dict(content)), sequence, created_at),
        )
        return AgentItem(item_id, session_id, turn_id, str(kind), dict(content), sequence, created_at)

    def create_session(
        self,
        agent_id: str,
        *,
        agent_version: str = "1",
        principal_id: str = "",
        environment_type: str = "none",
        state: Mapping[str, Any] | None = None,
        session_id: str | None = None,
        tenant_id: str = "",
    ) -> AgentSession:
        agent_id = str(agent_id or "").strip()
        agent_version = str(agent_version or "").strip()
        environment_type = str(environment_type or "").strip()
        if not agent_id or not agent_version:
            raise ValueError("agent_id and agent_version are required")
        if environment_type not in {"none", "self_hosted", "mesh"}:
            raise ValueError("unsupported environment_type")
        clean_tenant = self._validate_tenant_id(tenant_id)
        session_state = dict(state or {})
        if "tenant_id" in session_state:
            session_state["tenant_id"] = self._validate_tenant_id(session_state.get("tenant_id"))
        if clean_tenant:
            session_state["tenant_id"] = clean_tenant
        session_id = str(session_id or _new_id("sess"))
        timestamp = _now()
        with self._transaction() as connection:
            try:
                connection.execute(
                    """INSERT INTO agent_sessions
                       (session_id, agent_id, agent_version, status, principal_id,
                        environment_type, state_json, version, created_at, updated_at)
                       VALUES (?, ?, ?, ?, ?, ?, ?, 1, ?, ?)""",
                    (
                        session_id,
                        agent_id,
                        agent_version,
                        SessionStatus.READY.value,
                        str(principal_id),
                        environment_type,
                        _json(session_state),
                        timestamp,
                        timestamp,
                    ),
                )
            except sqlite3.IntegrityError as exc:
                raise SessionStateConflict(f"session already exists: {session_id}") from exc
            self._append_event(connection, session_id, "session.created", {
                "agent_id": agent_id,
                "agent_version": agent_version,
                "environment_type": environment_type,
            })
            row = self._require_session(connection, session_id)
            return self._session(row)

    def get_session(self, session_id: str) -> AgentSession:
        with self._lock:
            row = self._connection.execute(
                "SELECT * FROM agent_sessions WHERE session_id = ?", (str(session_id),)
            ).fetchone()
        if row is None:
            raise KeyError(f"unknown agent session: {session_id}")
        return self._session(row)

    def create_task(
        self,
        agent_id: str,
        model: str,
        input_items: str | Mapping[str, Any] | Sequence[Mapping[str, Any]],
        *,
        agent_version: str = "1",
        principal_id: str = "",
        environment_type: str = "none",
        session_id: str | None = None,
        turn_id: str | None = None,
        priority: int = 0,
        deadline_at: float | None = None,
        tenant_id: str = "",
        routing: Mapping[str, Any] | None = None,
    ) -> tuple[AgentSession, AgentTurn]:
        """Atomically create a model-bound session and its first queued turn."""
        clean_agent = str(agent_id or "").strip()
        clean_version = str(agent_version or "").strip()
        clean_model = str(model or "").strip()
        clean_environment = str(environment_type or "").strip()
        if not clean_agent or not clean_version:
            raise ValueError("agent_id and agent_version are required")
        if not 1 <= len(clean_model) <= 256:
            raise ValueError("model must be between 1 and 256 characters")
        if clean_environment not in {"none", "self_hosted", "mesh"}:
            raise ValueError("unsupported environment_type")
        clean_priority, clean_deadline = self._validate_turn_schedule(priority, deadline_at)
        clean_tenant = self._validate_tenant_id(tenant_id)
        clean_routing = self._validate_routing_requirements(clean_model, routing)
        items = _items(input_items)
        clean_session_id = str(session_id or _new_id("sess"))
        clean_turn_id = str(turn_id or _new_id("turn"))
        timestamp = _now()
        with self._transaction() as connection:
            try:
                connection.execute(
                    """INSERT INTO agent_sessions
                       (session_id, agent_id, agent_version, status, principal_id,
                        environment_type, state_json, version, created_at, updated_at)
                       VALUES (?, ?, ?, ?, ?, ?, ?, 1, ?, ?)""",
                    (
                        clean_session_id,
                        clean_agent,
                        clean_version,
                        SessionStatus.READY.value,
                        str(principal_id),
                        clean_environment,
                        _json({
                            "model": clean_model,
                            **({"tenant_id": clean_tenant} if clean_tenant else {}),
                            **({"routing": clean_routing} if clean_routing else {}),
                        }),
                        timestamp,
                        timestamp,
                    ),
                )
                self._append_event(connection, clean_session_id, "session.created", {
                    "agent_id": clean_agent,
                    "agent_version": clean_version,
                    "environment_type": clean_environment,
                    "task_created": True,
                })
                connection.execute(
                    """INSERT INTO agent_turns
                       (turn_id, session_id, status, version, error, created_at, updated_at,
                        priority, deadline_at)
                       VALUES (?, ?, ?, 1, '', ?, ?, ?, ?)""",
                    (
                        clean_turn_id,
                        clean_session_id,
                        TurnStatus.QUEUED.value,
                        timestamp,
                        timestamp,
                        clean_priority,
                        clean_deadline,
                    ),
                )
                for item in items:
                    self._append_item(connection, clean_session_id, clean_turn_id, "input", item)
                session_row = self._require_session(connection, clean_session_id)
                self._set_session_status(connection, session_row, SessionStatus.RUNNING, reason="task_created")
                self._append_event(connection, clean_session_id, "turn.created", {
                    "turn_id": clean_turn_id,
                    "item_count": len(items),
                    "model_bound": True,
                    "priority": clean_priority,
                    "deadline_at": clean_deadline,
                }, turn_id=clean_turn_id)
            except sqlite3.IntegrityError as exc:
                raise SessionStateConflict("task session or turn already exists") from exc
            return (
                self._session(self._require_session(connection, clean_session_id)),
                self._turn(self._require_turn(connection, clean_turn_id)),
            )

    def get_turn(self, turn_id: str) -> AgentTurn:
        with self._lock:
            row = self._connection.execute(
                "SELECT * FROM agent_turns WHERE turn_id = ?", (str(turn_id),)
            ).fetchone()
        if row is None:
            raise KeyError(f"unknown agent turn: {turn_id}")
        return self._turn(row)

    def get_turn_checkpoint(self, turn_id: str) -> dict[str, Any] | None:
        """Return the private bounded execution checkpoint for one turn."""
        with self._lock:
            row = self._connection.execute(
                "SELECT checkpoint_json FROM agent_turns WHERE turn_id = ?", (str(turn_id),)
            ).fetchone()
        if row is None:
            raise KeyError(f"unknown agent turn: {turn_id}")
        raw = str(row["checkpoint_json"] or "")
        if not raw:
            return None
        try:
            value = json.loads(raw)
        except (TypeError, ValueError) as exc:
            raise SessionStateConflict("turn checkpoint is corrupt") from exc
        if not isinstance(value, dict):
            raise SessionStateConflict("turn checkpoint must be an object")
        return value

    def checkpoint_turn(
        self,
        turn_id: str,
        checkpoint: Mapping[str, Any] | None,
    ) -> AgentTurn:
        """Persist or clear a private, bounded in-flight execution checkpoint."""
        if checkpoint is None:
            encoded = ""
            payload: dict[str, Any] = {"cleared": True}
        else:
            if not isinstance(checkpoint, Mapping):
                raise TypeError("turn checkpoint must be a mapping or None")
            encoded = _json(dict(checkpoint))
            encoded_size = len(encoded.encode("utf-8"))
            if encoded_size > _MAX_TURN_CHECKPOINT_BYTES:
                raise ValueError("turn checkpoint exceeds the 4 MiB limit")
            payload = {
                "phase": str(checkpoint.get("phase") or "unknown")[:64],
                "iteration": checkpoint.get("iteration", 0),
                "checkpoint_bytes": encoded_size,
            }
        with self._transaction() as connection:
            row = self._require_turn(connection, str(turn_id))
            timestamp = _now()
            connection.execute(
                """UPDATE agent_turns
                   SET checkpoint_json = ?, version = version + 1, updated_at = ?
                   WHERE turn_id = ?""",
                (encoded, timestamp, str(turn_id)),
            )
            self._append_event(
                connection,
                str(row["session_id"]),
                "turn.checkpointed",
                payload,
                turn_id=str(turn_id),
            )
            return self._turn(self._require_turn(connection, str(turn_id)))

    def list_turns(
        self,
        *,
        statuses: Sequence[TurnStatus | str] | None = None,
        session_id: str | None = None,
        limit: int = 100,
    ) -> list[AgentTurn]:
        """Return a bounded deterministic page of durable turns."""
        page_limit = max(1, min(int(limit), 500))
        query = "SELECT * FROM agent_turns WHERE 1=1"
        params: list[Any] = []
        if statuses is not None:
            normalized = [TurnStatus(status).value for status in statuses]
            if not normalized:
                return []
            query += " AND status IN (" + ",".join("?" for _ in normalized) + ")"
            params.extend(normalized)
        if session_id is not None:
            query += " AND session_id = ?"
            params.append(str(session_id))
        query += """ ORDER BY priority DESC,
                            CASE WHEN deadline_at IS NULL THEN 1 ELSE 0 END,
                            deadline_at ASC, created_at ASC, turn_id ASC LIMIT ?"""
        params.append(page_limit)
        with self._lock:
            rows = self._connection.execute(query, params).fetchall()
        return [self._turn(row) for row in rows]

    def expire_queued_turn(self, turn_id: str, *, now: float | None = None) -> AgentTurn | None:
        """Fail a queued turn whose admission deadline has elapsed.

        This is atomic with the claim boundary, so a worker cannot execute a
        turn after another worker has expired it. Running turns are left to
        the harness deadline/cancellation policy instead.
        """
        timestamp = _now() if now is None else float(now)
        if not math.isfinite(timestamp):
            raise ValueError("now must be a finite timestamp")
        with self._transaction() as connection:
            row = self._require_turn(connection, str(turn_id))
            deadline = row["deadline_at"]
            current = TurnStatus(str(row["status"]))
            if deadline is None or float(deadline) > timestamp:
                return None
            if current not in {TurnStatus.QUEUED, TurnStatus.RESUMING}:
                return None
            return self._apply_turn_status(
                connection,
                row,
                TurnStatus.FAILED,
                error="deadline_exceeded",
                reason="turn_admission_deadline_exceeded",
            )

    def claim_turn(self, turn_id: str, *, worker_id: str) -> AgentTurn | None:
        """Atomically claim one queued/resuming turn for a worker.

        The status transition is the durable lease. If the process disappears
        after the claim, the normal restart recovery changes the running turn
        to ``paused`` instead of allowing an unbounded replay.
        """
        clean_worker = str(worker_id or "").strip()
        if not clean_worker or len(clean_worker) > 128:
            raise ValueError("worker_id must be between 1 and 128 characters")
        with self._transaction() as connection:
            row = self._require_turn(connection, str(turn_id))
            current = TurnStatus(str(row["status"]))
            if current not in {TurnStatus.QUEUED, TurnStatus.RESUMING}:
                return None
            pending_control = connection.execute(
                """SELECT 1 FROM agent_controls
                   WHERE session_id = ? AND (turn_id = ? OR turn_id IS NULL)
                     AND status = ? AND action IN (?, ?)
                   ORDER BY created_at DESC LIMIT 1""",
                (
                    str(row["session_id"]),
                    str(turn_id),
                    ControlStatus.REQUESTED.value,
                    ControlAction.PAUSE.value,
                    ControlAction.CANCEL.value,
                ),
            ).fetchone()
            if pending_control is not None:
                return None
            timestamp = _now()
            connection.execute(
                "UPDATE agent_turns SET status = ?, version = version + 1, error = '', updated_at = ? WHERE turn_id = ?",
                (TurnStatus.RUNNING.value, timestamp, str(turn_id)),
            )
            session = self._require_session(connection, str(row["session_id"]))
            if SessionStatus(str(session["status"])) is not SessionStatus.RUNNING:
                self._set_session_status(connection, session, SessionStatus.RUNNING, reason="turn_claimed")
            self._append_event(connection, str(row["session_id"]), "turn.claimed", {
                "turn_id": str(turn_id),
                "worker_id": clean_worker,
                "from": current.value,
            }, turn_id=str(turn_id))
            return self._turn(self._require_turn(connection, str(turn_id)))

    def _authorize_control(
        self,
        session: sqlite3.Row,
        *,
        principal_id: str | None,
        is_admin: bool,
    ) -> None:
        if is_admin:
            return
        owner = str(session["principal_id"] or "")
        caller = str(principal_id or "")
        if not owner or not caller or not hmac.compare_digest(owner, caller):
            raise PermissionError("control does not belong to the authenticated principal")

    def _set_control_status(
        self,
        connection: sqlite3.Connection,
        row: sqlite3.Row,
        status: ControlStatus,
        *,
        reason: str = "",
    ) -> AgentControl:
        timestamp = _now()
        connection.execute(
            "UPDATE agent_controls SET status = ?, resolved_at = ?, reason = ? WHERE control_id = ?",
            (status.value, timestamp, str(reason)[:512], str(row["control_id"])),
        )
        event_type = "control.applied" if status is ControlStatus.APPLIED else "control.rejected"
        self._append_event(
            connection,
            str(row["session_id"]),
            event_type,
            {
                "control_id": str(row["control_id"]),
                "action": str(row["action"]),
                "reason": str(reason)[:256],
            },
            turn_id=str(row["turn_id"]) if row["turn_id"] is not None else None,
        )
        updated = connection.execute(
            "SELECT * FROM agent_controls WHERE control_id = ?", (str(row["control_id"]),)
        ).fetchone()
        assert updated is not None
        return self._control(updated)

    def _apply_turn_status(
        self,
        connection: sqlite3.Connection,
        row: sqlite3.Row,
        target: TurnStatus,
        *,
        error: str = "",
        reason: str = "",
    ) -> AgentTurn:
        current = TurnStatus(str(row["status"]))
        if target is not current and target not in _TURN_TRANSITIONS[current]:
            raise SessionStateConflict(f"invalid turn transition: {current.value} -> {target.value}")
        timestamp = _now()
        version = int(row["version"]) + (1 if target is not current else 0)
        connection.execute(
            "UPDATE agent_turns SET status = ?, version = ?, error = ?, updated_at = ? WHERE turn_id = ?",
            (target.value, version, str(error), timestamp, str(row["turn_id"])),
        )
        self._append_event(connection, str(row["session_id"]), "turn.status_changed", {
            "turn_id": str(row["turn_id"]),
            "from": current.value,
            "to": target.value,
            "error": str(error),
            "reason": reason,
        }, turn_id=str(row["turn_id"]))
        session = self._require_session(connection, str(row["session_id"]))
        session_target = {
            TurnStatus.RUNNING: SessionStatus.RUNNING,
            TurnStatus.WAITING_FOR_TOOL: SessionStatus.WAITING_FOR_TOOL,
            TurnStatus.WAITING_FOR_APPROVAL: SessionStatus.WAITING_FOR_APPROVAL,
            TurnStatus.WAITING_FOR_SUBAGENTS: SessionStatus.WAITING_FOR_SUBAGENTS,
            TurnStatus.COMPACTING: SessionStatus.COMPACTING,
            TurnStatus.PAUSED: SessionStatus.PAUSED,
            TurnStatus.COMPLETED: SessionStatus.READY,
            TurnStatus.FAILED: SessionStatus.FAILED,
            TurnStatus.CANCELLED: SessionStatus.READY,
        }.get(target)
        if session_target is not None and SessionStatus(str(session["status"])) is not session_target:
            self._set_session_status(connection, session, session_target, reason=f"turn_{target.value}")
        return self._turn(self._require_turn(connection, str(row["turn_id"])))

    def request_control(
        self,
        session_id: str,
        action: ControlAction | str,
        *,
        principal_id: str | None,
        turn_id: str | None = None,
        is_admin: bool = False,
        control_id: str | None = None,
    ) -> AgentControl:
        """Request pause/resume/cancel with durable, idempotent semantics.

        A running worker observes pending controls at safe loop boundaries. A
        queued or waiting turn is changed atomically here so it cannot be
        claimed by a worker between the API response and the next poll.
        """
        target_action = ControlAction(action)
        with self._transaction() as connection:
            session = self._require_session(connection, str(session_id))
            self._authorize_control(session, principal_id=principal_id, is_admin=is_admin)
            selected_turn = None
            if turn_id is not None:
                selected_turn = self._require_turn(connection, str(turn_id))
                if str(selected_turn["session_id"]) != str(session_id):
                    raise SessionStateConflict("control turn belongs to a different session")
            else:
                selected_turn = connection.execute(
                    """SELECT * FROM agent_turns WHERE session_id = ?
                       ORDER BY CASE WHEN status IN (?, ?, ?, ?, ?, ?, ?) THEN 0 ELSE 1 END,
                                created_at DESC, turn_id DESC LIMIT 1""",
                    (
                        str(session_id),
                        TurnStatus.QUEUED.value,
                        TurnStatus.RUNNING.value,
                        TurnStatus.WAITING_FOR_TOOL.value,
                        TurnStatus.WAITING_FOR_APPROVAL.value,
                        TurnStatus.WAITING_FOR_SUBAGENTS.value,
                        TurnStatus.COMPACTING.value,
                        TurnStatus.RESUMING.value,
                    ),
                ).fetchone()
            selected_turn_id = str(selected_turn["turn_id"]) if selected_turn is not None else None
            existing = connection.execute(
                """SELECT * FROM agent_controls
                   WHERE session_id = ? AND (turn_id = ? OR (turn_id IS NULL AND ? IS NULL))
                     AND action = ? AND status = ?
                   ORDER BY created_at DESC LIMIT 1""",
                (
                    str(session_id), selected_turn_id, selected_turn_id,
                    target_action.value, ControlStatus.REQUESTED.value,
                ),
            ).fetchone()
            if existing is not None:
                return self._control(existing)
            created_at = _now()
            clean_id = str(control_id or _new_id("ctrl"))
            connection.execute(
                """INSERT INTO agent_controls
                   (control_id, session_id, turn_id, action, status, principal_id, created_at, resolved_at, reason)
                   VALUES (?, ?, ?, ?, ?, ?, ?, NULL, '')""",
                (
                    clean_id, str(session_id), selected_turn_id, target_action.value,
                    ControlStatus.REQUESTED.value, str(principal_id or ""), created_at,
                ),
            )
            self._append_event(connection, str(session_id), "control.requested", {
                "control_id": clean_id,
                "action": target_action.value,
            }, turn_id=selected_turn_id)
            control_row = connection.execute(
                "SELECT * FROM agent_controls WHERE control_id = ?", (clean_id,)
            ).fetchone()
            assert control_row is not None

            current_turn = TurnStatus(str(selected_turn["status"])) if selected_turn is not None else None
            safe_to_apply = selected_turn is None or current_turn is not TurnStatus.RUNNING
            if target_action is ControlAction.RESUME:
                session_status = SessionStatus(str(session["status"]))
                if session_status not in {SessionStatus.PAUSED, SessionStatus.FAILED}:
                    raise SessionStateConflict(f"session cannot resume in state: {session_status.value}")
                if selected_turn is None or current_turn not in {TurnStatus.PAUSED, TurnStatus.FAILED}:
                    raise SessionStateConflict("resume requires a paused or failed turn")
                resumed = self._apply_turn_status(
                    connection, selected_turn, TurnStatus.RESUMING, reason="control_resume"
                )
                self._set_session_status(
                    connection,
                    self._require_session(connection, str(session_id)),
                    SessionStatus.RESUMING,
                    reason="control_resume",
                )
                ready = self._set_session_status(
                    connection,
                    self._require_session(connection, str(session_id)),
                    SessionStatus.READY,
                    reason="control_resume_ready",
                )
                self._append_event(connection, str(session_id), "session.resumed", {"reason": "control_resume"})
                return self._set_control_status(connection, control_row, ControlStatus.APPLIED, reason="resuming")

            if target_action is ControlAction.PAUSE and current_turn is None:
                session_status = SessionStatus(str(session["status"]))
                if session_status in {SessionStatus.RUNNING, SessionStatus.READY}:
                    self._set_session_status(connection, session, SessionStatus.PAUSED, reason="control_pause")
                    return self._set_control_status(connection, control_row, ControlStatus.APPLIED, reason="paused")
            if safe_to_apply and selected_turn is not None:
                target_status = TurnStatus.PAUSED if target_action is ControlAction.PAUSE else TurnStatus.CANCELLED
                self._apply_turn_status(connection, selected_turn, target_status, reason=f"control_{target_action.value}")
                return self._set_control_status(connection, control_row, ControlStatus.APPLIED, reason=target_status.value)
            return self._control(control_row)

    def get_pending_control(self, session_id: str, turn_id: str) -> AgentControl | None:
        with self._lock:
            row = self._connection.execute(
                """SELECT * FROM agent_controls
                   WHERE session_id = ? AND (turn_id = ? OR turn_id IS NULL)
                     AND status = ? AND action IN (?, ?)
                   ORDER BY CASE WHEN action = ? THEN 0 ELSE 1 END, created_at DESC LIMIT 1""",
                (
                    str(session_id), str(turn_id), ControlStatus.REQUESTED.value,
                    ControlAction.CANCEL.value, ControlAction.PAUSE.value, ControlAction.CANCEL.value,
                ),
            ).fetchone()
        return self._control(row) if row is not None else None

    def apply_pending_control(self, session_id: str, turn_id: str, action: ControlAction | str) -> AgentControl:
        """Apply the pending active-worker control after a safe loop boundary."""
        target_action = ControlAction(action)
        with self._transaction() as connection:
            row = connection.execute(
                """SELECT * FROM agent_controls
                   WHERE session_id = ? AND (turn_id = ? OR turn_id IS NULL)
                     AND action = ? AND status = ?
                   ORDER BY created_at DESC LIMIT 1""",
                (str(session_id), str(turn_id), target_action.value, ControlStatus.REQUESTED.value),
            ).fetchone()
            if row is None:
                raise SessionStateConflict("no pending control exists")
            turn = self._require_turn(connection, str(turn_id))
            current = TurnStatus(str(turn["status"]))
            if target_action is ControlAction.PAUSE:
                target = TurnStatus.PAUSED
            elif target_action is ControlAction.CANCEL:
                target = TurnStatus.CANCELLED
            else:
                raise SessionStateConflict("resume is not an active-worker control")
            if current not in {target, TurnStatus.RUNNING, TurnStatus.WAITING_FOR_TOOL, TurnStatus.WAITING_FOR_SUBAGENTS, TurnStatus.COMPACTING}:
                return self._set_control_status(connection, row, ControlStatus.REJECTED, reason=f"turn_{current.value}")
            if current is not target:
                self._apply_turn_status(connection, turn, target, reason=f"control_{target_action.value}")
            return self._set_control_status(connection, row, ControlStatus.APPLIED, reason=target.value)

    def list_sessions(self, *, principal_id: str | None = None, limit: int = 100) -> list[AgentSession]:
        """Return bounded session metadata, newest activity first."""
        page_limit = max(1, min(int(limit), 500))
        query = "SELECT * FROM agent_sessions"
        params: list[Any] = []
        if principal_id is not None:
            query += " WHERE principal_id = ?"
            params.append(str(principal_id))
        query += " ORDER BY updated_at DESC, session_id DESC LIMIT ?"
        params.append(page_limit)
        with self._lock:
            rows = self._connection.execute(query, params).fetchall()
        return [self._session(row) for row in rows]

    def create_approval(
        self,
        session_id: str,
        *,
        turn_id: str | None,
        tool_id: str,
        call_id: str,
        arguments_digest: str,
        principal_id: str,
        ttl_seconds: float = 300.0,
        approval_id: str | None = None,
    ) -> Approval:
        """Persist one exact side-effect decision request, reusing a pending duplicate."""
        clean_tool = str(tool_id or "").strip()
        clean_call = str(call_id or "").strip()
        clean_principal = str(principal_id or "").strip()
        clean_digest = str(arguments_digest or "").strip()
        if not clean_tool or not clean_call or not clean_principal:
            raise ValueError("tool_id, call_id and principal_id are required")
        if not re.fullmatch(r"[A-Fa-f0-9]{64}", clean_digest):
            raise ValueError("arguments_digest must be a SHA-256 digest")
        expires_at = _now() + min(max(float(ttl_seconds), 1.0), 3600.0)
        with self._transaction() as connection:
            session = self._require_session(connection, str(session_id))
            if turn_id is not None:
                turn = self._require_turn(connection, str(turn_id))
                if str(turn["session_id"]) != str(session_id):
                    raise SessionStateConflict("approval turn belongs to a different session")
            existing = connection.execute(
                """SELECT * FROM agent_approvals
                   WHERE session_id = ? AND tool_id = ? AND call_id = ?
                     AND arguments_digest = ? AND status = ? AND expires_at > ?
                   ORDER BY created_at DESC LIMIT 1""",
                (str(session_id), clean_tool, clean_call, clean_digest, ApprovalStatus.PENDING.value, _now()),
            ).fetchone()
            if existing is not None:
                return self._approval(existing)
            created_at = _now()
            clean_id = str(approval_id or _new_id("approval"))
            connection.execute(
                """INSERT INTO agent_approvals
                   (approval_id, session_id, turn_id, tool_id, call_id, arguments_digest,
                    principal_id, status, expires_at, created_at, resolved_at, resolution_reason)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, NULL, '')""",
                (
                    clean_id,
                    str(session_id),
                    str(turn_id) if turn_id is not None else None,
                    clean_tool,
                    clean_call,
                    clean_digest,
                    clean_principal,
                    ApprovalStatus.PENDING.value,
                    expires_at,
                    created_at,
                ),
            )
            self._append_event(connection, str(session_id), "approval.required", {
                "approval_id": clean_id,
                "tool_id": clean_tool,
                "call_id": clean_call,
                "arguments_digest": clean_digest,
                "expires_at": expires_at,
            }, turn_id=turn_id)
            row = connection.execute("SELECT * FROM agent_approvals WHERE approval_id = ?", (clean_id,)).fetchone()
            assert row is not None
            return self._approval(row)

    def get_approval(self, approval_id: str) -> Approval:
        with self._lock:
            row = self._connection.execute(
                "SELECT * FROM agent_approvals WHERE approval_id = ?", (str(approval_id),)
            ).fetchone()
        if row is None:
            raise KeyError(f"unknown agent approval: {approval_id}")
        return self._approval(row)

    def list_approvals(
        self,
        *,
        principal_id: str | None = None,
        session_id: str | None = None,
        status: ApprovalStatus | str | None = None,
        limit: int = 100,
    ) -> list[Approval]:
        page_limit = max(1, min(int(limit), 500))
        query = "SELECT * FROM agent_approvals WHERE 1=1"
        params: list[Any] = []
        if principal_id is not None:
            query += " AND principal_id = ?"
            params.append(str(principal_id))
        if session_id is not None:
            query += " AND session_id = ?"
            params.append(str(session_id))
        if status is not None:
            query += " AND status = ?"
            params.append(ApprovalStatus(status).value)
        query += " ORDER BY created_at DESC, approval_id DESC LIMIT ?"
        params.append(page_limit)
        with self._lock:
            rows = self._connection.execute(query, params).fetchall()
        return [self._approval(row) for row in rows]

    def resolve_approval(
        self,
        approval_id: str,
        *,
        principal_id: str | None,
        decision: ApprovalStatus | str,
        reason: str = "",
        is_admin: bool = False,
    ) -> Approval:
        target = ApprovalStatus(decision)
        if target not in {ApprovalStatus.APPROVED, ApprovalStatus.REJECTED}:
            raise ValueError("approval decision must be approved or rejected")
        clean_reason = str(reason or "")[:512]
        with self._transaction() as connection:
            row = connection.execute(
                "SELECT * FROM agent_approvals WHERE approval_id = ?", (str(approval_id),)
            ).fetchone()
            if row is None:
                raise KeyError(f"unknown agent approval: {approval_id}")
            owner = str(row["principal_id"])
            caller = str(principal_id or "")
            if not is_admin and (not caller or not hmac.compare_digest(owner, caller)):
                raise PermissionError("approval does not belong to the authenticated principal")
            current = ApprovalStatus(str(row["status"]))
            if current is not ApprovalStatus.PENDING:
                raise SessionStateConflict(f"approval is already {current.value}")
            now = _now()
            if float(row["expires_at"]) <= now:
                connection.execute(
                    "UPDATE agent_approvals SET status = ?, resolved_at = ?, resolution_reason = ? WHERE approval_id = ?",
                    (ApprovalStatus.EXPIRED.value, now, "approval_expired", str(approval_id)),
                )
                self._append_event(connection, str(row["session_id"]), "approval.expired", {
                    "approval_id": str(approval_id),
                    "tool_id": str(row["tool_id"]),
                }, turn_id=str(row["turn_id"]) if row["turn_id"] is not None else None)
                raise SessionStateConflict("approval has expired")
            connection.execute(
                "UPDATE agent_approvals SET status = ?, resolved_at = ?, resolution_reason = ? WHERE approval_id = ?",
                (target.value, now, clean_reason, str(approval_id)),
            )
            event_type = "approval.granted" if target is ApprovalStatus.APPROVED else "approval.denied"
            self._append_event(connection, str(row["session_id"]), event_type, {
                "approval_id": str(approval_id),
                "tool_id": str(row["tool_id"]),
                "reason_present": bool(clean_reason),
            }, turn_id=str(row["turn_id"]) if row["turn_id"] is not None else None)
            updated = connection.execute("SELECT * FROM agent_approvals WHERE approval_id = ?", (str(approval_id),)).fetchone()
            assert updated is not None
            return self._approval(updated)

    def consume_approval(
        self,
        approval_id: str,
        *,
        session_id: str,
        turn_id: str | None,
        tool_id: str,
        arguments_digest: str,
    ) -> Approval:
        """Consume one approved action after its exact request is rebuilt.

        The store deliberately keeps only the digest, never the raw arguments.
        A resumed caller must therefore present the same tool and digest.  The
        atomic status transition makes an approved side effect one-shot across
        process restarts and concurrent resume attempts.
        """
        with self._transaction() as connection:
            row = connection.execute(
                "SELECT * FROM agent_approvals WHERE approval_id = ?",
                (str(approval_id),),
            ).fetchone()
            if row is None:
                raise KeyError(f"unknown agent approval: {approval_id}")
            if str(row["session_id"]) != str(session_id):
                raise SessionStateConflict("approval belongs to a different session")
            if turn_id is not None and str(row["turn_id"] or "") != str(turn_id):
                raise SessionStateConflict("approval belongs to a different turn")
            if str(row["tool_id"]) != str(tool_id):
                raise SessionStateConflict("approved tool does not match the requested tool")
            if not hmac.compare_digest(str(row["arguments_digest"]), str(arguments_digest)):
                raise SessionStateConflict("approved arguments do not match the requested arguments")
            status = ApprovalStatus(str(row["status"]))
            if status is not ApprovalStatus.APPROVED:
                raise SessionStateConflict(f"approval is not executable: {status.value}")
            connection.execute(
                "UPDATE agent_approvals SET status = ? WHERE approval_id = ?",
                (ApprovalStatus.CONSUMED.value, str(approval_id)),
            )
            self._append_event(connection, str(session_id), "approval.consumed", {
                "approval_id": str(approval_id),
                "tool_id": str(tool_id),
                "arguments_digest": str(arguments_digest),
            }, turn_id=str(turn_id) if turn_id is not None else None)
            updated = connection.execute(
                "SELECT * FROM agent_approvals WHERE approval_id = ?", (str(approval_id),)
            ).fetchone()
            assert updated is not None
            return self._approval(updated)

    def resume_approved_turn(self, approval_id: str) -> AgentTurn:
        """Move a waiting turn into resumable state without executing it."""
        with self._transaction() as connection:
            approval_row = connection.execute(
                "SELECT * FROM agent_approvals WHERE approval_id = ?", (str(approval_id),)
            ).fetchone()
            if approval_row is None:
                raise KeyError(f"unknown agent approval: {approval_id}")
            if ApprovalStatus(str(approval_row["status"])) is not ApprovalStatus.APPROVED:
                raise SessionStateConflict("only an approved action can resume a turn")
            turn_id = approval_row["turn_id"]
            if turn_id is None:
                raise SessionStateConflict("approval is not attached to a turn")
            row = self._require_turn(connection, str(turn_id))
            current = TurnStatus(str(row["status"]))
            if current is not TurnStatus.WAITING_FOR_APPROVAL:
                raise SessionStateConflict(f"turn is not waiting for approval: {current.value}")
            if TurnStatus.RESUMING not in _TURN_TRANSITIONS[current]:
                raise SessionStateConflict("waiting turn cannot be resumed")
            timestamp = _now()
            connection.execute(
                "UPDATE agent_turns SET status = ?, version = version + 1, updated_at = ? WHERE turn_id = ?",
                (TurnStatus.RESUMING.value, timestamp, str(turn_id)),
            )
            self._append_event(connection, str(approval_row["session_id"]), "turn.resuming", {
                "turn_id": str(turn_id),
                "approval_id": str(approval_id),
            }, turn_id=str(turn_id))
            return self._turn(self._require_turn(connection, str(turn_id)))

    def start_turn(
        self,
        session_id: str,
        input_items: str | Mapping[str, Any] | Sequence[Mapping[str, Any]],
        *,
        turn_id: str | None = None,
        priority: int = 0,
        deadline_at: float | None = None,
    ) -> AgentTurn:
        items = _items(input_items)
        turn_id = str(turn_id or _new_id("turn"))
        clean_priority, clean_deadline = self._validate_turn_schedule(priority, deadline_at)
        timestamp = _now()
        with self._transaction() as connection:
            session = self._require_session(connection, str(session_id))
            status = SessionStatus(str(session["status"]))
            if status is not SessionStatus.READY:
                raise SessionStateConflict(f"session is not ready for a new turn: {status.value}")
            active_statuses = tuple(_ACTIVE_TURN_STATUSES)
            active_turn = connection.execute(
                """SELECT turn_id FROM agent_turns
                   WHERE session_id = ? AND status IN ("""
                + ",".join("?" for _ in active_statuses)
                + ") LIMIT 1",
                (str(session_id), *(turn_status.value for turn_status in active_statuses)),
            ).fetchone()
            if active_turn is not None:
                raise SessionStateConflict("session already has an active turn")
            try:
                connection.execute(
                    """INSERT INTO agent_turns
                       (turn_id, session_id, status, version, error, created_at, updated_at,
                        priority, deadline_at)
                       VALUES (?, ?, ?, 1, '', ?, ?, ?, ?)""",
                    (
                        turn_id,
                        str(session_id),
                        TurnStatus.QUEUED.value,
                        timestamp,
                        timestamp,
                        clean_priority,
                        clean_deadline,
                    ),
                )
            except sqlite3.IntegrityError as exc:
                raise SessionStateConflict(f"turn already exists: {turn_id}") from exc
            for item in items:
                self._append_item(connection, str(session_id), turn_id, "input", item)
            self._set_session_status(connection, session, SessionStatus.RUNNING, reason="turn_started")
            self._append_event(connection, str(session_id), "turn.created", {
                "turn_id": turn_id,
                "item_count": len(items),
                "priority": clean_priority,
                "deadline_at": clean_deadline,
            }, turn_id=turn_id)
            row = self._require_turn(connection, turn_id)
            return self._turn(row)

    def steer_turn(
        self,
        session_id: str,
        turn_id: str,
        input_items: str | Mapping[str, Any] | Sequence[Mapping[str, Any]],
    ) -> AgentItem:
        items = _items(input_items)
        if len(items) != 1:
            raise ValueError("steering accepts exactly one item")
        with self._transaction() as connection:
            session = self._require_session(connection, str(session_id))
            turn = self._require_turn(connection, str(turn_id))
            if str(turn["session_id"]) != str(session_id):
                raise SessionStateConflict("turn belongs to a different session")
            turn_status = TurnStatus(str(turn["status"]))
            if turn_status not in _ACTIVE_TURN_STATUSES - {TurnStatus.QUEUED}:
                raise SessionStateConflict(f"turn cannot be steered in state: {turn_status.value}")
            item = self._append_item(connection, str(session_id), str(turn_id), "steering", items[0])
            self._append_event(connection, str(session_id), "turn.steered", {
                "turn_id": str(turn_id),
                "item_id": item.item_id,
                "content_digest": hashlib.sha256(_json(items[0]).encode("utf-8")).hexdigest(),
            }, turn_id=str(turn_id))
            return item

    def record_item(
        self,
        session_id: str,
        turn_id: str,
        kind: str,
        content: Mapping[str, Any],
    ) -> AgentItem:
        """Persist a model/tool item without changing lifecycle state."""
        with self._transaction() as connection:
            turn = self._require_turn(connection, str(turn_id))
            if str(turn["session_id"]) != str(session_id):
                raise SessionStateConflict("turn belongs to a different session")
            return self._append_item(connection, str(session_id), str(turn_id), str(kind), content)

    def record_event(
        self,
        session_id: str,
        event_type: str,
        payload: Mapping[str, Any] | None = None,
        *,
        turn_id: str | None = None,
    ) -> SessionEvent:
        """Append a redacted event for adapters and executors."""
        with self._transaction() as connection:
            self._require_session(connection, str(session_id))
            if turn_id is not None:
                turn = self._require_turn(connection, str(turn_id))
                if str(turn["session_id"]) != str(session_id):
                    raise SessionStateConflict("turn belongs to a different session")
            return self._append_event(connection, str(session_id), str(event_type), payload, turn_id=turn_id)

    def _set_session_status(
        self,
        connection: sqlite3.Connection,
        row: sqlite3.Row,
        target: SessionStatus,
        *,
        reason: str = "",
    ) -> AgentSession:
        current = SessionStatus(str(row["status"]))
        if target is not current and target not in _SESSION_TRANSITIONS[current]:
            raise SessionStateConflict(f"invalid session transition: {current.value} -> {target.value}")
        timestamp = _now()
        version = int(row["version"]) + (1 if target is not current else 0)
        connection.execute(
            "UPDATE agent_sessions SET status = ?, version = ?, updated_at = ? WHERE session_id = ?",
            (target.value, version, timestamp, str(row["session_id"])),
        )
        if target is not current:
            self._append_event(connection, str(row["session_id"]), "session.status_changed", {
                "from": current.value,
                "to": target.value,
                "reason": reason,
            })
        return self._session(self._require_session(connection, str(row["session_id"])))

    def transition_session(
        self,
        session_id: str,
        target: SessionStatus,
        *,
        expected_version: int | None = None,
        reason: str = "",
    ) -> AgentSession:
        target = SessionStatus(target)
        with self._transaction() as connection:
            row = self._require_session(connection, str(session_id))
            if expected_version is not None and int(row["version"]) != int(expected_version):
                raise SessionStateConflict("session version changed")
            return self._set_session_status(connection, row, target, reason=reason)

    def transition_turn(
        self,
        turn_id: str,
        target: TurnStatus,
        *,
        expected_version: int | None = None,
        error: str = "",
        reason: str = "",
    ) -> AgentTurn:
        target = TurnStatus(target)
        with self._transaction() as connection:
            row = self._require_turn(connection, str(turn_id))
            current = TurnStatus(str(row["status"]))
            if expected_version is not None and int(row["version"]) != int(expected_version):
                raise SessionStateConflict("turn version changed")
            if target is not current and target not in _TURN_TRANSITIONS[current]:
                raise SessionStateConflict(f"invalid turn transition: {current.value} -> {target.value}")
            timestamp = _now()
            version = int(row["version"]) + (1 if target is not current else 0)
            connection.execute(
                "UPDATE agent_turns SET status = ?, version = ?, error = ?, updated_at = ? WHERE turn_id = ?",
                (target.value, version, str(error), timestamp, str(turn_id)),
            )
            session = self._require_session(connection, str(row["session_id"]))
            self._append_event(connection, str(row["session_id"]), "turn.status_changed", {
                "turn_id": str(turn_id),
                "from": current.value,
                "to": target.value,
                "error": str(error),
                "reason": reason,
            }, turn_id=str(turn_id))
            session_target = {
                TurnStatus.RUNNING: SessionStatus.RUNNING,
                TurnStatus.WAITING_FOR_TOOL: SessionStatus.WAITING_FOR_TOOL,
                TurnStatus.WAITING_FOR_APPROVAL: SessionStatus.WAITING_FOR_APPROVAL,
                TurnStatus.WAITING_FOR_SUBAGENTS: SessionStatus.WAITING_FOR_SUBAGENTS,
                TurnStatus.COMPACTING: SessionStatus.COMPACTING,
                TurnStatus.PAUSED: SessionStatus.PAUSED,
                TurnStatus.COMPLETED: SessionStatus.READY,
                TurnStatus.FAILED: SessionStatus.FAILED,
                TurnStatus.CANCELLED: SessionStatus.READY,
            }.get(target)
            if session_target is not None and SessionStatus(str(session["status"])) is not session_target:
                self._set_session_status(connection, session, session_target, reason=f"turn_{target.value}")
            return self._turn(self._require_turn(connection, str(turn_id)))

    def resume_session(self, session_id: str, *, reason: str = "resume") -> AgentSession:
        with self._transaction() as connection:
            row = self._require_session(connection, str(session_id))
            status = SessionStatus(str(row["status"]))
            if status not in {SessionStatus.PAUSED, SessionStatus.FAILED}:
                raise SessionStateConflict(f"session cannot resume in state: {status.value}")
            resumed = self._set_session_status(connection, row, SessionStatus.RESUMING, reason=reason)
            ready = self._set_session_status(
                connection,
                self._require_session(connection, resumed.session_id),
                SessionStatus.READY,
                reason="resume_ready",
            )
            self._append_event(connection, ready.session_id, "session.resumed", {"reason": reason})
            return ready

    def checkpoint(self, session_id: str, checkpoint: Mapping[str, Any]) -> AgentSession:
        with self._transaction() as connection:
            row = self._require_session(connection, str(session_id))
            state = json.loads(str(row["state_json"]))
            state["checkpoint"] = dict(checkpoint)
            timestamp = _now()
            connection.execute(
                "UPDATE agent_sessions SET state_json = ?, version = version + 1, updated_at = ? WHERE session_id = ?",
                (_json(state), timestamp, str(session_id)),
            )
            self._append_event(connection, str(session_id), "session.checkpointed", {
                "checkpoint_keys": sorted(str(key) for key in checkpoint),
            })
            return self._session(self._require_session(connection, str(session_id)))

    def recover_interrupted(self) -> list[str]:
        """Pause work left active after a process restart; never replay it blindly."""
        recovered: list[str] = []
        with self._transaction() as connection:
            # Queued work was never claimed by a worker and is therefore
            # safe to pick up after restart. Only in-flight states need the
            # explicit pause/resume boundary to prevent blind replay.
            recoverable_statuses = _ACTIVE_TURN_STATUSES - {TurnStatus.QUEUED}
            placeholders = ", ".join("?" for _ in recoverable_statuses)
            rows = connection.execute(
                f"SELECT * FROM agent_turns WHERE status IN ({placeholders})",
                tuple(status.value for status in recoverable_statuses),
            ).fetchall()
            for turn in rows:
                turn_id = str(turn["turn_id"])
                timestamp = _now()
                connection.execute(
                    "UPDATE agent_turns SET status = ?, version = version + 1, error = ?, updated_at = ? WHERE turn_id = ?",
                    (TurnStatus.PAUSED.value, "runtime_restarted", timestamp, turn_id),
                )
                self._append_event(connection, str(turn["session_id"]), "turn.interrupted", {
                    "turn_id": turn_id,
                    "reason": "runtime_restarted",
                }, turn_id=turn_id)
                session = self._require_session(connection, str(turn["session_id"]))
                if SessionStatus(str(session["status"])) not in {SessionStatus.PAUSED, SessionStatus.CANCELLED, SessionStatus.EXPIRED}:
                    self._set_session_status(connection, session, SessionStatus.PAUSED, reason="runtime_restarted")
                recovered.append(turn_id)
        return recovered

    def list_items(self, session_id: str, *, turn_id: str | None = None) -> list[AgentItem]:
        query = "SELECT * FROM agent_items WHERE session_id = ?"
        params: list[Any] = [str(session_id)]
        if turn_id is not None:
            query += " AND turn_id = ?"
            params.append(str(turn_id))
        query += " ORDER BY sequence"
        with self._lock:
            rows = self._connection.execute(query, params).fetchall()
        return [
            AgentItem(
                str(row["item_id"]),
                str(row["session_id"]),
                str(row["turn_id"]),
                str(row["kind"]),
                json.loads(str(row["content_json"])),
                int(row["sequence"]),
                float(row["created_at"]),
            )
            for row in rows
        ]

    def list_events(self, session_id: str, *, after_sequence: int = 0, limit: int = 100) -> list[SessionEvent]:
        with self._lock:
            rows = self._connection.execute(
                """SELECT * FROM agent_events
                   WHERE session_id = ? AND sequence > ?
                   ORDER BY sequence LIMIT ?""",
                (str(session_id), max(0, int(after_sequence)), max(1, min(int(limit), 1000))),
            ).fetchall()
        return [self._event(row) for row in rows]

    def read_event_page(
        self,
        session_id: str,
        *,
        after_sequence: int = 0,
        limit: int = 100,
        wait_seconds: float = 0.0,
    ) -> EventPage:
        """Read a bounded event page, optionally waiting for the next event.

        The cursor is the durable per-session sequence, not a process-local
        offset. A reconnecting client can therefore resume safely after an
        app restart. Waiting is deliberately bounded and polling-based so the
        store remains usable with SQLite and does not require a new transport.
        """
        cursor = max(0, int(after_sequence))
        page_limit = max(1, min(int(limit), 1000))
        deadline = time.monotonic() + max(0.0, min(float(wait_seconds), 30.0))
        while True:
            events = self.list_events(session_id, after_sequence=cursor, limit=page_limit + 1)
            if events or time.monotonic() >= deadline:
                visible = tuple(events[:page_limit])
                next_sequence = visible[-1].sequence if visible else cursor
                return EventPage(visible, next_sequence, len(events) > page_limit)
            time.sleep(min(0.05, max(0.0, deadline - time.monotonic())))

    def pending_events(self, *, limit: int = 100) -> list[SessionEvent]:
        with self._lock:
            rows = self._connection.execute(
                "SELECT * FROM agent_events WHERE dispatched_at IS NULL ORDER BY created_at LIMIT ?",
                (max(1, min(int(limit), 1000)),),
            ).fetchall()
        return [self._event(row) for row in rows]

    @staticmethod
    def _validate_outbox_consumer(consumer_id: str) -> str:
        value = str(consumer_id or "").strip()
        if not re.fullmatch(r"[A-Za-z0-9_.:-]{1,160}", value):
            raise ValueError("consumer_id must be a bounded identifier")
        return value

    def claim_pending_events(
        self,
        consumer_id: str,
        *,
        limit: int = 100,
        lease_seconds: float = 60.0,
    ) -> list[SessionEvent]:
        """Claim a bounded event batch for one dispatcher consumer.

        Claims are leases rather than delivery acknowledgements. A crashed
        consumer's events become claimable again after the lease expires, and
        the durable event cursor remains unchanged for reconnecting clients.
        """
        consumer = self._validate_outbox_consumer(consumer_id)
        try:
            lease = float(lease_seconds)
        except (TypeError, ValueError) as exc:
            raise ValueError("lease_seconds must be a positive finite number") from exc
        if not math.isfinite(lease) or not 0.01 <= lease <= 86_400.0:
            raise ValueError("lease_seconds must be between 0.01 and 86400")
        page_limit = max(1, min(int(limit), 1000))
        now = _now()
        with self._transaction() as connection:
            rows = connection.execute(
                """SELECT event_id FROM agent_events
                   WHERE dispatched_at IS NULL
                     AND (claimed_at IS NULL OR claim_expires_at IS NULL OR claim_expires_at <= ?)
                   ORDER BY created_at, sequence LIMIT ?""",
                (now, page_limit),
            ).fetchall()
            event_ids = [str(row["event_id"]) for row in rows]
            for event_id in event_ids:
                connection.execute(
                    """UPDATE agent_events
                       SET claimed_by = ?, claimed_at = ?, claim_expires_at = ?, outbox_attempts = outbox_attempts + 1
                       WHERE event_id = ? AND dispatched_at IS NULL
                         AND (claimed_at IS NULL OR claim_expires_at IS NULL OR claim_expires_at <= ?)""",
                    (consumer, now, now + lease, event_id, now),
                )
            if not event_ids:
                return []
            placeholders = ", ".join("?" for _ in event_ids)
            claimed = connection.execute(
                f"SELECT * FROM agent_events WHERE event_id IN ({placeholders}) AND claimed_by = ? ORDER BY created_at, sequence",
                (*event_ids, consumer),
            ).fetchall()
        return [self._event(row) for row in claimed]

    def ack_pending_events(self, consumer_id: str, event_ids: Sequence[str]) -> int:
        """Mark claimed events delivered, accepting only their current owner."""
        consumer = self._validate_outbox_consumer(consumer_id)
        ids = tuple(dict.fromkeys(str(value) for value in event_ids if str(value).strip()))
        if not ids:
            return 0
        if len(ids) > 1000:
            raise ValueError("at most 1000 event IDs may be acknowledged")
        timestamp = _now()
        with self._transaction() as connection:
            changed = 0
            for event_id in ids:
                changed += connection.execute(
                    """UPDATE agent_events
                       SET dispatched_at = ?, claimed_by = NULL, claimed_at = NULL, claim_expires_at = NULL
                       WHERE event_id = ? AND dispatched_at IS NULL AND claimed_by = ?""",
                    (timestamp, event_id, consumer),
                ).rowcount
            return changed

    def release_pending_events(self, consumer_id: str, event_ids: Sequence[str]) -> int:
        """Release claims after a failed delivery so another worker can retry."""
        consumer = self._validate_outbox_consumer(consumer_id)
        ids = tuple(dict.fromkeys(str(value) for value in event_ids if str(value).strip()))
        if not ids:
            return 0
        if len(ids) > 1000:
            raise ValueError("at most 1000 event IDs may be released")
        with self._transaction() as connection:
            changed = 0
            for event_id in ids:
                changed += connection.execute(
                    """UPDATE agent_events
                       SET claimed_by = NULL, claimed_at = NULL, claim_expires_at = NULL
                       WHERE event_id = ? AND dispatched_at IS NULL AND claimed_by = ?""",
                    (event_id, consumer),
                ).rowcount
            return changed

    def mark_event_dispatched(self, event_id: str) -> SessionEvent:
        with self._transaction() as connection:
            timestamp = _now()
            changed = connection.execute(
                """UPDATE agent_events
                   SET dispatched_at = ?, claimed_by = NULL, claimed_at = NULL, claim_expires_at = NULL
                   WHERE event_id = ?""",
                (timestamp, str(event_id)),
            ).rowcount
            if not changed:
                raise KeyError(f"unknown agent event: {event_id}")
            row = connection.execute("SELECT * FROM agent_events WHERE event_id = ?", (str(event_id),)).fetchone()
            assert row is not None
            return self._event(row)

    def close(self) -> None:
        with self._lock:
            self._connection.close()

    def __enter__(self) -> AgentSessionStore:
        return self

    def __exit__(self, *exc: Any) -> None:
        self.close()
