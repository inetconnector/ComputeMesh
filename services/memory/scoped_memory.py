"""Scoped, provenance-aware Memory v2 for ComputeMesh Agents Platform."""
from __future__ import annotations

from dataclasses import asdict, dataclass
from enum import Enum
import hashlib
import json
from pathlib import Path
import sqlite3
import threading
import time
from typing import Any, Iterable, Mapping, Sequence
import uuid


class MemoryScope(str, Enum):
    USER = "USER"
    FLEET = "FLEET"
    PROJECT = "PROJECT"
    SESSION = "SESSION"
    GLOBAL = "GLOBAL"


class MemoryKind(str, Enum):
    FACT = "FACT"
    PREFERENCE = "PREFERENCE"
    DECISION = "DECISION"
    GOAL = "GOAL"
    ROUTINE = "ROUTINE"
    CORRECTION = "CORRECTION"
    TEMPORARY = "TEMPORARY"
    NEGATIVE_CONSTRAINT = "NEGATIVE_CONSTRAINT"


class Sensitivity(str, Enum):
    PUBLIC = "PUBLIC"
    INTERNAL = "INTERNAL"
    PERSONAL = "PERSONAL"
    SENSITIVE = "SENSITIVE"
    SECRET = "SECRET"


@dataclass(frozen=True)
class MemoryRecord:
    memory_id: str
    scope: MemoryScope
    scope_id: str
    kind: MemoryKind
    key: str
    value: str
    source: str
    provenance: str
    confidence: float
    authority: float
    explicit: bool
    sensitivity: Sensitivity
    consent: str
    purpose: str
    valid_from: float
    valid_until: float | None
    supersedes: str | None
    active: bool
    created_at: float
    updated_at: float
    metadata: Mapping[str, Any]

    def to_dict(self) -> dict[str, Any]:
        value = asdict(self)
        value["scope"] = self.scope.value
        value["kind"] = self.kind.value
        value["sensitivity"] = self.sensitivity.value
        return value


class ScopedMemoryStore:
    """SQLite memory store with strict scope isolation, expiry and provenance."""

    def __init__(self, db_path: str | Path = ":memory:") -> None:
        self.db_path = str(db_path)
        if self.db_path != ":memory:":
            Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(self.db_path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._lock = threading.RLock()
        with self._conn:
            self._conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS memories (
                    memory_id TEXT PRIMARY KEY,
                    scope TEXT NOT NULL,
                    scope_id TEXT NOT NULL,
                    kind TEXT NOT NULL,
                    key TEXT NOT NULL,
                    value TEXT NOT NULL,
                    source TEXT NOT NULL,
                    provenance TEXT NOT NULL,
                    confidence REAL NOT NULL,
                    authority REAL NOT NULL,
                    explicit INTEGER NOT NULL,
                    sensitivity TEXT NOT NULL,
                    consent TEXT NOT NULL,
                    purpose TEXT NOT NULL,
                    valid_from REAL NOT NULL,
                    valid_until REAL,
                    supersedes TEXT,
                    active INTEGER NOT NULL,
                    created_at REAL NOT NULL,
                    updated_at REAL NOT NULL,
                    metadata_json TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_memory_scope ON memories(scope, scope_id, active);
                CREATE INDEX IF NOT EXISTS idx_memory_key ON memories(key, active);
                CREATE INDEX IF NOT EXISTS idx_memory_expiry ON memories(valid_until, active);
                CREATE TABLE IF NOT EXISTS suppressions (
                    suppression_id TEXT PRIMARY KEY,
                    scope TEXT NOT NULL,
                    scope_id TEXT NOT NULL,
                    key_pattern TEXT NOT NULL,
                    reason TEXT NOT NULL,
                    created_at REAL NOT NULL
                );
                """
            )

    @staticmethod
    def _clean_key(key: str) -> str:
        return "_".join(str(key or "").strip().casefold().split())

    @staticmethod
    def _scope_id(scope: MemoryScope, scope_id: str | None) -> str:
        if scope == MemoryScope.GLOBAL:
            return "global"
        value = str(scope_id or "").strip()
        if not value:
            raise ValueError(f"scope_id is required for {scope.value}")
        return value

    @staticmethod
    def _row(row: sqlite3.Row) -> MemoryRecord:
        return MemoryRecord(
            memory_id=row["memory_id"], scope=MemoryScope(row["scope"]), scope_id=row["scope_id"],
            kind=MemoryKind(row["kind"]), key=row["key"], value=row["value"], source=row["source"],
            provenance=row["provenance"], confidence=float(row["confidence"]), authority=float(row["authority"]),
            explicit=bool(row["explicit"]), sensitivity=Sensitivity(row["sensitivity"]), consent=row["consent"],
            purpose=row["purpose"], valid_from=float(row["valid_from"]),
            valid_until=None if row["valid_until"] is None else float(row["valid_until"]),
            supersedes=row["supersedes"], active=bool(row["active"]), created_at=float(row["created_at"]),
            updated_at=float(row["updated_at"]), metadata=json.loads(row["metadata_json"] or "{}"),
        )

    def put(
        self,
        *,
        scope: MemoryScope | str,
        scope_id: str | None,
        kind: MemoryKind | str,
        key: str,
        value: str,
        source: str,
        provenance: str = "",
        confidence: float = 1.0,
        authority: float = 1.0,
        explicit: bool = True,
        sensitivity: Sensitivity | str = Sensitivity.PERSONAL,
        consent: str = "explicit",
        purpose: str = "personalization",
        ttl_seconds: float | None = None,
        supersedes: str | None = None,
        metadata: Mapping[str, Any] | None = None,
    ) -> MemoryRecord:
        scope_obj = scope if isinstance(scope, MemoryScope) else MemoryScope(str(scope).upper())
        kind_obj = kind if isinstance(kind, MemoryKind) else MemoryKind(str(kind).upper())
        sens_obj = sensitivity if isinstance(sensitivity, Sensitivity) else Sensitivity(str(sensitivity).upper())
        sid = self._scope_id(scope_obj, scope_id)
        clean_key = self._clean_key(key)
        clean_value = str(value or "").strip()
        if not clean_key or not clean_value:
            raise ValueError("memory key and value are required")
        if not 0.0 <= float(confidence) <= 1.0 or not 0.0 <= float(authority) <= 1.0:
            raise ValueError("confidence and authority must be between 0 and 1")
        if sens_obj in {Sensitivity.SENSITIVE, Sensitivity.SECRET} and not str(consent).strip():
            raise ValueError("sensitive memory requires an explicit consent marker")
        now = time.time()
        valid_until = None if ttl_seconds is None else now + max(0.0, float(ttl_seconds))
        memory_id = f"mem_{uuid.uuid4().hex}"
        record = MemoryRecord(
            memory_id=memory_id, scope=scope_obj, scope_id=sid, kind=kind_obj, key=clean_key,
            value=clean_value, source=str(source or "unknown"), provenance=str(provenance or ""),
            confidence=float(confidence), authority=float(authority), explicit=bool(explicit), sensitivity=sens_obj,
            consent=str(consent or ""), purpose=str(purpose or ""), valid_from=now, valid_until=valid_until,
            supersedes=supersedes, active=True, created_at=now, updated_at=now, metadata=dict(metadata or {}),
        )
        with self._lock, self._conn:
            if supersedes:
                self._conn.execute("UPDATE memories SET active=0,updated_at=? WHERE memory_id=?", (now, supersedes))
            self._conn.execute(
                """INSERT INTO memories(memory_id,scope,scope_id,kind,key,value,source,provenance,confidence,authority,
                explicit,sensitivity,consent,purpose,valid_from,valid_until,supersedes,active,created_at,updated_at,metadata_json)
                VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (record.memory_id, record.scope.value, record.scope_id, record.kind.value, record.key, record.value,
                 record.source, record.provenance, record.confidence, record.authority, int(record.explicit),
                 record.sensitivity.value, record.consent, record.purpose, record.valid_from, record.valid_until,
                 record.supersedes, 1, record.created_at, record.updated_at,
                 json.dumps(record.metadata, ensure_ascii=False, sort_keys=True)),
            )
        return record

    def suppress(self, *, scope: MemoryScope | str, scope_id: str | None, key_pattern: str, reason: str) -> str:
        scope_obj = scope if isinstance(scope, MemoryScope) else MemoryScope(str(scope).upper())
        sid = self._scope_id(scope_obj, scope_id)
        pattern = self._clean_key(key_pattern)
        suppression_id = f"sup_{uuid.uuid4().hex}"
        with self._lock, self._conn:
            self._conn.execute(
                "INSERT INTO suppressions(suppression_id,scope,scope_id,key_pattern,reason,created_at) VALUES(?,?,?,?,?,?)",
                (suppression_id, scope_obj.value, sid, pattern, str(reason), time.time()),
            )
        return suppression_id

    def _suppressed_patterns(self, scope: MemoryScope, scope_id: str) -> tuple[str, ...]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT key_pattern FROM suppressions WHERE scope=? AND scope_id=?", (scope.value, scope_id)
            ).fetchall()
        return tuple(str(row["key_pattern"]) for row in rows)

    def expire(self) -> int:
        now = time.time()
        with self._lock, self._conn:
            cursor = self._conn.execute(
                "UPDATE memories SET active=0,updated_at=? WHERE active=1 AND valid_until IS NOT NULL AND valid_until<=?",
                (now, now),
            )
            return cursor.rowcount

    def delete(self, memory_id: str) -> bool:
        with self._lock, self._conn:
            cursor = self._conn.execute("UPDATE memories SET active=0,updated_at=? WHERE memory_id=?", (time.time(), memory_id))
            if cursor.rowcount:
                self._conn.execute("UPDATE memories SET active=0,updated_at=? WHERE supersedes=?", (time.time(), memory_id))
            return bool(cursor.rowcount)

    def retrieve(
        self,
        *,
        scopes: Sequence[tuple[MemoryScope | str, str | None]],
        query: str = "",
        limit: int = 20,
        include_sensitive: bool = False,
        include_inactive: bool = False,
    ) -> list[MemoryRecord]:
        self.expire()
        query_tokens = {token for token in self._clean_key(query).replace("_", " ").split() if token}
        ranked: list[tuple[float, MemoryRecord]] = []
        now = time.time()
        scope_rank = {MemoryScope.SESSION: 5.0, MemoryScope.PROJECT: 4.0, MemoryScope.USER: 3.0, MemoryScope.FLEET: 2.0, MemoryScope.GLOBAL: 1.0}
        for raw_scope, raw_sid in scopes:
            scope = raw_scope if isinstance(raw_scope, MemoryScope) else MemoryScope(str(raw_scope).upper())
            sid = self._scope_id(scope, raw_sid)
            suppressions = self._suppressed_patterns(scope, sid)
            with self._lock:
                rows = self._conn.execute(
                    "SELECT * FROM memories WHERE scope=? AND scope_id=?" + ("" if include_inactive else " AND active=1"),
                    (scope.value, sid),
                ).fetchall()
            for row in rows:
                record = self._row(row)
                if record.sensitivity in {Sensitivity.SENSITIVE, Sensitivity.SECRET} and not include_sensitive:
                    continue
                if any(pattern and pattern in record.key for pattern in suppressions):
                    continue
                haystack = f"{record.key} {record.value} {record.kind.value} {record.source}".casefold()
                lexical = sum(1.0 for token in query_tokens if token in haystack)
                if query_tokens and lexical == 0:
                    continue
                recency = 1.0 / (1.0 + max(0.0, now - record.updated_at) / 86400.0)
                score = scope_rank[scope] + lexical * 1.8 + record.authority * 1.4 + record.confidence + recency
                if record.kind == MemoryKind.NEGATIVE_CONSTRAINT:
                    score += 3.0
                if record.explicit:
                    score += 0.5
                ranked.append((score, record))
        ranked.sort(key=lambda item: (-item[0], -item[1].updated_at, item[1].memory_id))
        return [record for _, record in ranked[: max(1, int(limit))]]

    def conflicts(self, *, scope: MemoryScope | str, scope_id: str | None, key: str) -> list[MemoryRecord]:
        scope_obj = scope if isinstance(scope, MemoryScope) else MemoryScope(str(scope).upper())
        sid = self._scope_id(scope_obj, scope_id)
        clean_key = self._clean_key(key)
        with self._lock:
            rows = self._conn.execute(
                "SELECT * FROM memories WHERE scope=? AND scope_id=? AND key=? AND active=1 ORDER BY updated_at DESC",
                (scope_obj.value, sid, clean_key),
            ).fetchall()
        records = [self._row(row) for row in rows]
        distinct_values = {record.value for record in records}
        return records if len(distinct_values) > 1 else []

    def export_scope(self, *, scope: MemoryScope | str, scope_id: str | None, include_inactive: bool = True) -> dict[str, Any]:
        scope_obj = scope if isinstance(scope, MemoryScope) else MemoryScope(str(scope).upper())
        sid = self._scope_id(scope_obj, scope_id)
        with self._lock:
            rows = self._conn.execute(
                "SELECT * FROM memories WHERE scope=? AND scope_id=?" + ("" if include_inactive else " AND active=1") + " ORDER BY created_at",
                (scope_obj.value, sid),
            ).fetchall()
        return {"scope": scope_obj.value, "scope_id": sid, "memories": [self._row(row).to_dict() for row in rows]}

    def import_legacy_json(self, path: str | Path, *, user_scope_id: str, source: str = "legacy_user_memory") -> dict[str, Any]:
        legacy_path = Path(path)
        payload = json.loads(legacy_path.read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            raise ValueError("legacy memory root must be an object")
        imported: list[str] = []
        skipped: list[str] = []
        digest = hashlib.sha256(legacy_path.read_bytes()).hexdigest()
        profile = payload.get("profile") if isinstance(payload.get("profile"), dict) else {}
        for pref in profile.get("preferences", []) if isinstance(profile.get("preferences"), list) else []:
            record = self.put(scope=MemoryScope.USER, scope_id=user_scope_id, kind=MemoryKind.PREFERENCE,
                              key=f"legacy_preference_{len(imported)+1}", value=str(pref), source=source,
                              provenance=f"{legacy_path}:{digest}", explicit=True, sensitivity=Sensitivity.PERSONAL,
                              consent="legacy_import", purpose="migration")
            imported.append(record.memory_id)
        for fact in profile.get("facts", []) if isinstance(profile.get("facts"), list) else []:
            record = self.put(scope=MemoryScope.USER, scope_id=user_scope_id, kind=MemoryKind.FACT,
                              key=f"legacy_fact_{len(imported)+1}", value=str(fact), source=source,
                              provenance=f"{legacy_path}:{digest}", explicit=True, sensitivity=Sensitivity.PERSONAL,
                              consent="legacy_import", purpose="migration")
            imported.append(record.memory_id)
        memories = payload.get("memories") if isinstance(payload.get("memories"), dict) else {}
        for key, item in memories.items():
            if not isinstance(item, dict) or not str(item.get("value", "")).strip():
                skipped.append(str(key))
                continue
            category = str(item.get("category", "general")).casefold()
            kind = MemoryKind.PREFERENCE if "pref" in category else MemoryKind.FACT
            record = self.put(scope=MemoryScope.USER, scope_id=user_scope_id, kind=kind, key=str(key),
                              value=str(item["value"]), source=source, provenance=f"{legacy_path}:{digest}",
                              explicit=True, sensitivity=Sensitivity.PERSONAL, consent="legacy_import", purpose="migration",
                              metadata={"legacy_category": category, "legacy_updated_at": item.get("updated_at")})
            imported.append(record.memory_id)
        return {"imported": imported, "skipped": skipped, "source_checksum": digest}

    def summary(self, *, scopes: Sequence[tuple[MemoryScope | str, str | None]], query: str = "", limit: int = 12) -> str:
        records = self.retrieve(scopes=scopes, query=query, limit=limit, include_sensitive=False)
        if not records:
            return ""
        lines = ["### Scoped memory context"]
        for record in records:
            lines.append(f"- [{record.scope.value}/{record.kind.value}] {record.key}: {record.value} (source={record.source}, confidence={record.confidence:.2f})")
        return "\n".join(lines)
