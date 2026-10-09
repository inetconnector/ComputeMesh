"""Small durable trace store for session, turn and tool observability."""
from __future__ import annotations

import json
import re
import sqlite3
import threading
import time
import uuid
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterator, Mapping

_SENSITIVE = re.compile(r"(token|secret|password|credential|authorization|api[_-]?key|private[_-]?key)", re.I)


@dataclass(frozen=True)
class TraceSpan:
    span_id: str
    trace_id: str
    parent_span_id: str | None
    session_id: str
    turn_id: str | None
    kind: str
    name: str
    status: str
    started_at: float
    ended_at: float | None
    attributes: Mapping[str, Any]


class TraceStore:
    """Persist redacted spans without storing prompts, outputs or secrets."""

    def __init__(self, path: str | Path = ":memory:") -> None:
        self.path = Path(path)
        if str(path) != ":memory:":
            self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._connection = sqlite3.connect(str(path), check_same_thread=False, timeout=30.0)
        self._connection.row_factory = sqlite3.Row
        self._connection.execute("PRAGMA busy_timeout = 30000")
        if str(path) != ":memory:":
            self._connection.execute("PRAGMA journal_mode = WAL")
        self._create_schema()

    def _create_schema(self) -> None:
        with self._transaction() as connection:
            connection.execute(
                """CREATE TABLE IF NOT EXISTS trace_spans (
                    span_id TEXT PRIMARY KEY,
                    trace_id TEXT NOT NULL,
                    parent_span_id TEXT,
                    session_id TEXT NOT NULL,
                    turn_id TEXT,
                    kind TEXT NOT NULL,
                    name TEXT NOT NULL,
                    status TEXT NOT NULL,
                    started_at REAL NOT NULL,
                    ended_at REAL,
                    attributes_json TEXT NOT NULL
                )"""
            )
            connection.execute("CREATE INDEX IF NOT EXISTS trace_session_idx ON trace_spans(session_id, started_at)")

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
    def _attributes(attributes: Mapping[str, Any] | None) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in (attributes or {}).items():
            name = str(key)
            if _SENSITIVE.search(name):
                result[name] = "[REDACTED]"
            elif isinstance(value, (str, int, float, bool)) or value is None:
                result[name] = value
            else:
                result[name] = str(value)[:512]
        return result

    @staticmethod
    def _span(row: sqlite3.Row) -> TraceSpan:
        return TraceSpan(
            span_id=str(row["span_id"]),
            trace_id=str(row["trace_id"]),
            parent_span_id=str(row["parent_span_id"]) if row["parent_span_id"] else None,
            session_id=str(row["session_id"]),
            turn_id=str(row["turn_id"]) if row["turn_id"] else None,
            kind=str(row["kind"]),
            name=str(row["name"]),
            status=str(row["status"]),
            started_at=float(row["started_at"]),
            ended_at=float(row["ended_at"]) if row["ended_at"] is not None else None,
            attributes=json.loads(str(row["attributes_json"])),
        )

    def start(
        self,
        *,
        session_id: str,
        turn_id: str | None,
        kind: str,
        name: str,
        trace_id: str | None = None,
        parent_span_id: str | None = None,
        attributes: Mapping[str, Any] | None = None,
    ) -> TraceSpan:
        span_id = f"span_{uuid.uuid4().hex}"
        now = time.time()
        with self._transaction() as connection:
            connection.execute(
                "INSERT INTO trace_spans (span_id, trace_id, parent_span_id, session_id, turn_id, kind, name, status, started_at, attributes_json) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (span_id, str(trace_id or f"trace_{session_id}_{turn_id or 'session'}"), parent_span_id, str(session_id), turn_id, str(kind), str(name), "running", now, json.dumps(self._attributes(attributes), sort_keys=True)),
            )
            return self._span(connection.execute("SELECT * FROM trace_spans WHERE span_id = ?", (span_id,)).fetchone())

    def finish(self, span_id: str, *, status: str = "completed", attributes: Mapping[str, Any] | None = None) -> TraceSpan:
        with self._transaction() as connection:
            row = connection.execute("SELECT * FROM trace_spans WHERE span_id = ?", (str(span_id),)).fetchone()
            if row is None:
                raise KeyError(f"unknown trace span: {span_id}")
            merged = dict(json.loads(str(row["attributes_json"])))
            merged.update(self._attributes(attributes))
            connection.execute("UPDATE trace_spans SET status = ?, ended_at = ?, attributes_json = ? WHERE span_id = ?", (str(status), time.time(), json.dumps(merged, sort_keys=True), str(span_id)))
            return self._span(connection.execute("SELECT * FROM trace_spans WHERE span_id = ?", (str(span_id),)).fetchone())

    def list_for_session(self, session_id: str) -> tuple[TraceSpan, ...]:
        with self._lock:
            # Wall-clock timestamps can share the same float resolution for a
            # parent and its immediately-created child. SQLite rowid preserves
            # insertion order and therefore keeps trace trees deterministic.
            rows = self._connection.execute("SELECT * FROM trace_spans WHERE session_id = ? ORDER BY rowid", (str(session_id),)).fetchall()
        return tuple(self._span(row) for row in rows)

    def close(self) -> None:
        with self._lock:
            self._connection.close()

    def __enter__(self) -> "TraceStore":
        return self

    def __exit__(self, *exc: Any) -> None:
        self.close()
