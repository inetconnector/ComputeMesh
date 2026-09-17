"""Scoped, provenance-aware persistent memory for ComputeMesh Agents Platform.

This module complements the legacy JSON user-memory store. It deliberately keeps
legacy import explicit and does not silently promote inferred content into facts.
Mutating operations are scope-bound so possession of a memory id alone never
grants authority to overwrite or delete another principal's memory.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from enum import Enum
import hashlib
import json
from pathlib import Path
import re
import sqlite3
import threading
import time
from typing import Any, Mapping, Sequence
import uuid


class MemoryType(str, Enum):
    FACT = "FACT"
    PREFERENCE = "PREFERENCE"
    DECISION = "DECISION"
    GOAL = "GOAL"
    ROUTINE = "ROUTINE"
    CORRECTION = "CORRECTION"
    TEMPORARY = "TEMPORARY"
    NEGATIVE_CONSTRAINT = "NEGATIVE_CONSTRAINT"


class MemoryScope(str, Enum):
    USER = "USER"
    FLEET = "FLEET"
    PROJECT = "PROJECT"
    SESSION = "SESSION"
    GLOBAL = "GLOBAL"


class Sensitivity(str, Enum):
    PUBLIC = "PUBLIC"
    INTERNAL = "INTERNAL"
    PERSONAL = "PERSONAL"
    SENSITIVE = "SENSITIVE"
    RESTRICTED = "RESTRICTED"


@dataclass(frozen=True)
class MemoryRecord:
    memory_id: str
    key: str
    value: str
    memory_type: MemoryType
    scope: MemoryScope
    scope_id: str
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
    derived_from: tuple[str, ...]
    created_at: float
    updated_at: float
    deleted_at: float | None = None

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["memory_type"] = self.memory_type.value
        data["scope"] = self.scope.value
        data["sensitivity"] = self.sensitivity.value
        data["derived_from"] = list(self.derived_from)
        return data


class StructuredMemoryStore:
    """SQLite memory store with scope isolation, expiry, provenance and deletion."""

    def __init__(self, db_path: str | Path = ":memory:") -> None:
        self.db_path = str(db_path)
        if self.db_path != ":memory:":
            Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._conn = sqlite3.connect(self.db_path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA foreign_keys=ON")
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._init_schema()

    def close(self) -> None:
        with self._lock:
            self._conn.close()

    def _init_schema(self) -> None:
        with self._lock, self._conn:
            self._conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS memories (
                    memory_id TEXT PRIMARY KEY,
                    key TEXT NOT NULL,
                    value TEXT NOT NULL,
                    memory_type TEXT NOT NULL,
                    scope TEXT NOT NULL,
                    scope_id TEXT NOT NULL,
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
                    derived_from_json TEXT NOT NULL,
                    created_at REAL NOT NULL,
                    updated_at REAL NOT NULL,
                    deleted_at REAL
                );
                CREATE INDEX IF NOT EXISTS idx_memory_scope ON memories(scope, scope_id);
                CREATE INDEX IF NOT EXISTS idx_memory_key ON memories(key);
                CREATE INDEX IF NOT EXISTS idx_memory_active ON memories(deleted_at, valid_until);
                CREATE TABLE IF NOT EXISTS suppressions (
                    suppression_id TEXT PRIMARY KEY,
                    scope TEXT NOT NULL,
                    scope_id TEXT NOT NULL,
                    key_pattern TEXT NOT NULL,
                    reason TEXT NOT NULL,
                    created_at REAL NOT NULL
                );
                CREATE TABLE IF NOT EXISTS migration_log (
                    migration_id TEXT PRIMARY KEY,
                    source TEXT NOT NULL,
                    source_checksum TEXT NOT NULL,
                    imported_count INTEGER NOT NULL,
                    created_at REAL NOT NULL
                );
                """
            )

    @staticmethod
    def _normalize_key(key: str) -> str:
        normalized = re.sub(r"[^a-z0-9_.-]+", "_", str(key or "").strip().casefold()).strip("_")
        if not normalized:
            raise ValueError("memory key is required")
        return normalized[:160]

    @staticmethod
    def _coerce_enum(enum_type: type[Enum], value: Any) -> Enum:
        if isinstance(value, enum_type):
            return value
        return enum_type(str(value).upper())

    @staticmethod
    def _validate_scope(scope: MemoryScope, scope_id: str) -> str:
        clean_scope_id = str(scope_id or "").strip()
        if scope is not MemoryScope.GLOBAL and not clean_scope_id:
            raise ValueError("scope_id is required outside GLOBAL scope")
        return clean_scope_id

    def put(
        self,
        key: str,
        value: str,
        *,
        memory_type: MemoryType | str = MemoryType.FACT,
        scope: MemoryScope | str = MemoryScope.USER,
        scope_id: str,
        provenance: str,
        confidence: float = 1.0,
        authority: float = 1.0,
        explicit: bool = True,
        sensitivity: Sensitivity | str = Sensitivity.PERSONAL,
        consent: str = "explicit",
        purpose: str = "future_context",
        valid_until: float | None = None,
        supersedes: str | None = None,
        derived_from: Sequence[str] = (),
    ) -> MemoryRecord:
        clean_key = self._normalize_key(key)
        clean_value = str(value or "").strip()
        if not clean_value:
            raise ValueError("memory value is required")
        scope_obj = self._coerce_enum(MemoryScope, scope)
        type_obj = self._coerce_enum(MemoryType, memory_type)
        sensitivity_obj = self._coerce_enum(Sensitivity, sensitivity)
        clean_scope_id = self._validate_scope(scope_obj, scope_id)
        confidence = min(1.0, max(0.0, float(confidence)))
        authority = min(1.0, max(0.0, float(authority)))
        now = time.time()

        if supersedes:
            with self._lock:
                previous = self._conn.execute(
                    "SELECT scope,scope_id,deleted_at FROM memories WHERE memory_id=?",
                    (supersedes,),
                ).fetchone()
            if previous is None:
                raise ValueError("superseded memory does not exist")
            if previous["deleted_at"] is not None:
                raise ValueError("superseded memory is already deleted")
            if previous["scope"] != scope_obj.value or previous["scope_id"] != clean_scope_id:
                raise PermissionError("cannot supersede memory from a different scope")

        for dependency in derived_from:
            with self._lock:
                source = self._conn.execute(
                    "SELECT scope,scope_id,deleted_at FROM memories WHERE memory_id=?",
                    (str(dependency),),
                ).fetchone()
            if source is None or source["deleted_at"] is not None:
                raise ValueError("derived memory references missing or deleted source")
            if source["scope"] != scope_obj.value or source["scope_id"] != clean_scope_id:
                raise PermissionError("derived memory cannot cross scope boundaries")

        record = MemoryRecord(
            memory_id=f"mem_{uuid.uuid4().hex}",
            key=clean_key,
            value=clean_value,
            memory_type=type_obj,
            scope=scope_obj,
            scope_id=clean_scope_id,
            provenance=str(provenance or "unknown"),
            confidence=confidence,
            authority=authority,
            explicit=bool(explicit),
            sensitivity=sensitivity_obj,
            consent=str(consent or ""),
            purpose=str(purpose or ""),
            valid_from=now,
            valid_until=valid_until,
            supersedes=supersedes,
            derived_from=tuple(str(x) for x in derived_from),
            created_at=now,
            updated_at=now,
        )
        if sensitivity_obj in {Sensitivity.SENSITIVE, Sensitivity.RESTRICTED} and not record.consent:
            raise ValueError("sensitive memory requires documented consent")
        with self._lock, self._conn:
            self._conn.execute(
                """
                INSERT INTO memories(memory_id,key,value,memory_type,scope,scope_id,provenance,confidence,authority,
                    explicit,sensitivity,consent,purpose,valid_from,valid_until,supersedes,derived_from_json,
                    created_at,updated_at,deleted_at)
                VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,NULL)
                """,
                (
                    record.memory_id, record.key, record.value, record.memory_type.value, record.scope.value,
                    record.scope_id, record.provenance, record.confidence, record.authority, int(record.explicit),
                    record.sensitivity.value, record.consent, record.purpose, record.valid_from, record.valid_until,
                    record.supersedes, json.dumps(record.derived_from), record.created_at, record.updated_at,
                ),
            )
            if supersedes:
                self._conn.execute(
                    "UPDATE memories SET deleted_at=?,updated_at=? "
                    "WHERE memory_id=? AND scope=? AND scope_id=? AND deleted_at IS NULL",
                    (now, now, supersedes, scope_obj.value, clean_scope_id),
                )
        return record

    def suppress(self, key_pattern: str, *, scope: MemoryScope | str, scope_id: str, reason: str) -> str:
        scope_obj = self._coerce_enum(MemoryScope, scope)
        clean_scope_id = self._validate_scope(scope_obj, scope_id)
        sid = f"sup_{uuid.uuid4().hex}"
        with self._lock, self._conn:
            self._conn.execute(
                "INSERT INTO suppressions(suppression_id,scope,scope_id,key_pattern,reason,created_at) VALUES(?,?,?,?,?,?)",
                (sid, scope_obj.value, clean_scope_id, self._normalize_key(key_pattern), str(reason), time.time()),
            )
        return sid

    def _suppressed_patterns(self, scope: MemoryScope, scope_id: str) -> tuple[str, ...]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT key_pattern FROM suppressions WHERE (scope=? AND scope_id=?) OR scope='GLOBAL'",
                (scope.value, scope_id),
            ).fetchall()
        return tuple(str(row["key_pattern"]) for row in rows)

    @staticmethod
    def _row_to_record(row: sqlite3.Row) -> MemoryRecord:
        return MemoryRecord(
            memory_id=row["memory_id"], key=row["key"], value=row["value"],
            memory_type=MemoryType(row["memory_type"]), scope=MemoryScope(row["scope"]),
            scope_id=row["scope_id"], provenance=row["provenance"], confidence=float(row["confidence"]),
            authority=float(row["authority"]), explicit=bool(row["explicit"]),
            sensitivity=Sensitivity(row["sensitivity"]), consent=row["consent"], purpose=row["purpose"],
            valid_from=float(row["valid_from"]), valid_until=row["valid_until"], supersedes=row["supersedes"],
            derived_from=tuple(json.loads(row["derived_from_json"] or "[]")), created_at=float(row["created_at"]),
            updated_at=float(row["updated_at"]), deleted_at=row["deleted_at"],
        )

    def get(
        self,
        memory_id: str,
        *,
        scope: MemoryScope | str | None = None,
        scope_id: str | None = None,
    ) -> MemoryRecord | None:
        query = "SELECT * FROM memories WHERE memory_id=?"
        params: list[Any] = [memory_id]
        if scope is not None:
            scope_obj = self._coerce_enum(MemoryScope, scope)
            clean_scope_id = self._validate_scope(scope_obj, str(scope_id or ""))
            query += " AND scope=? AND scope_id=?"
            params.extend([scope_obj.value, clean_scope_id])
        with self._lock:
            row = self._conn.execute(query, params).fetchone()
        return self._row_to_record(row) if row else None

    def list_active(
        self,
        *,
        scope: MemoryScope | str,
        scope_id: str,
        include_global: bool = True,
        now: float | None = None,
    ) -> list[MemoryRecord]:
        scope_obj = self._coerce_enum(MemoryScope, scope)
        clean_scope_id = self._validate_scope(scope_obj, scope_id)
        timestamp = time.time() if now is None else float(now)
        clauses = ["(scope=? AND scope_id=?)"]
        params: list[Any] = [scope_obj.value, clean_scope_id]
        if include_global:
            clauses.append("scope='GLOBAL'")
        query = (
            "SELECT * FROM memories WHERE deleted_at IS NULL AND valid_from<=? AND "
            "(valid_until IS NULL OR valid_until>?) AND (" + " OR ".join(clauses) + ")"
        )
        with self._lock:
            rows = self._conn.execute(query, [timestamp, timestamp, *params]).fetchall()
        suppressions = self._suppressed_patterns(scope_obj, clean_scope_id)
        result = [self._row_to_record(row) for row in rows]
        return [
            record for record in result
            if not any(record.key == pattern or record.key.startswith(pattern + ".") for pattern in suppressions)
        ]

    @staticmethod
    def _tokens(text: str) -> set[str]:
        return {tok for tok in re.findall(r"[\wäöüßÀ-ÿ.-]+", str(text).casefold()) if len(tok) > 1}

    def retrieve(
        self,
        query: str,
        *,
        scope: MemoryScope | str,
        scope_id: str,
        limit: int = 12,
        include_global: bool = True,
        now: float | None = None,
    ) -> list[MemoryRecord]:
        timestamp = time.time() if now is None else float(now)
        query_tokens = self._tokens(query)
        scored: list[tuple[float, MemoryRecord]] = []
        scope_obj = self._coerce_enum(MemoryScope, scope)
        for record in self.list_active(
            scope=scope_obj,
            scope_id=scope_id,
            include_global=include_global,
            now=timestamp,
        ):
            text_tokens = self._tokens(f"{record.key} {record.value} {record.memory_type.value}")
            overlap = len(query_tokens & text_tokens) / max(1, len(query_tokens)) if query_tokens else 0.0
            age_days = max(0.0, (timestamp - record.updated_at) / 86400.0)
            recency = 1.0 / (1.0 + age_days / 30.0)
            scope_bonus = 0.12 if record.scope == scope_obj and record.scope_id == scope_id else 0.0
            negative_bonus = 0.25 if record.memory_type == MemoryType.NEGATIVE_CONSTRAINT else 0.0
            score = (
                overlap * 0.48
                + record.authority * 0.22
                + record.confidence * 0.13
                + recency * 0.05
                + scope_bonus
                + negative_bonus
            )
            if query_tokens and overlap == 0 and record.memory_type != MemoryType.NEGATIVE_CONSTRAINT:
                continue
            scored.append((score, record))
        scored.sort(key=lambda item: (-item[0], -item[1].updated_at, item[1].memory_id))
        return [record for _, record in scored[: max(1, int(limit))]]

    def conflicts(self, key: str, *, scope: MemoryScope | str, scope_id: str) -> list[MemoryRecord]:
        clean_key = self._normalize_key(key)
        records = [
            record for record in self.list_active(scope=scope, scope_id=scope_id)
            if record.key == clean_key
        ]
        values = {record.value for record in records}
        return records if len(values) > 1 else []

    def delete(
        self,
        memory_id: str,
        *,
        scope: MemoryScope | str,
        scope_id: str,
        cascade_derived: bool = True,
    ) -> int:
        scope_obj = self._coerce_enum(MemoryScope, scope)
        clean_scope_id = self._validate_scope(scope_obj, scope_id)
        now = time.time()
        deleted = 0
        pending = [str(memory_id)]
        seen: set[str] = set()
        with self._lock, self._conn:
            while pending:
                current = pending.pop()
                if current in seen:
                    continue
                seen.add(current)
                cursor = self._conn.execute(
                    "UPDATE memories SET deleted_at=?,updated_at=? "
                    "WHERE memory_id=? AND scope=? AND scope_id=? AND deleted_at IS NULL",
                    (now, now, current, scope_obj.value, clean_scope_id),
                )
                deleted += cursor.rowcount
                if not cursor.rowcount or not cascade_derived:
                    continue
                rows = self._conn.execute(
                    "SELECT memory_id,derived_from_json FROM memories "
                    "WHERE deleted_at IS NULL AND scope=? AND scope_id=?",
                    (scope_obj.value, clean_scope_id),
                ).fetchall()
                for row in rows:
                    dependencies = set(json.loads(row["derived_from_json"] or "[]"))
                    if current in dependencies:
                        pending.append(str(row["memory_id"]))
        return deleted

    def purge_expired(self, *, now: float | None = None) -> int:
        timestamp = time.time() if now is None else float(now)
        with self._lock, self._conn:
            cursor = self._conn.execute(
                "UPDATE memories SET deleted_at=?,updated_at=? "
                "WHERE deleted_at IS NULL AND valid_until IS NOT NULL AND valid_until<=?",
                (timestamp, timestamp, timestamp),
            )
            return cursor.rowcount

    def export(self, *, scope: MemoryScope | str, scope_id: str) -> dict[str, Any]:
        scope_obj = self._coerce_enum(MemoryScope, scope)
        clean_scope_id = self._validate_scope(scope_obj, scope_id)
        with self._lock:
            rows = self._conn.execute(
                "SELECT * FROM memories WHERE scope=? AND scope_id=? ORDER BY created_at,memory_id",
                (scope_obj.value, clean_scope_id),
            ).fetchall()
        return {
            "schema_version": "1.1",
            "scope": scope_obj.value,
            "scope_id": clean_scope_id,
            "memories": [self._row_to_record(row).to_dict() for row in rows],
        }

    def import_legacy_json(
        self,
        path: str | Path,
        *,
        scope_id: str,
        provenance: str = "legacy_user_memory_json",
    ) -> dict[str, Any]:
        source = Path(path)
        raw = source.read_bytes()
        checksum = hashlib.sha256(raw).hexdigest()
        with self._lock:
            existing = self._conn.execute(
                "SELECT imported_count FROM migration_log WHERE source=? AND source_checksum=?",
                (str(source.resolve()), checksum),
            ).fetchone()
        if existing:
            return {
                "status": "already_imported",
                "imported": int(existing["imported_count"]),
                "checksum": checksum,
            }
        payload = json.loads(raw.decode("utf-8"))
        if not isinstance(payload, dict):
            raise ValueError("legacy memory root must be an object")
        imported = 0
        profile = payload.get("profile") if isinstance(payload.get("profile"), dict) else {}
        if profile.get("name"):
            self.put(
                "profile.name",
                str(profile["name"]),
                memory_type=MemoryType.FACT,
                scope=MemoryScope.USER,
                scope_id=scope_id,
                provenance=provenance,
            )
            imported += 1
        if profile.get("preferred_language"):
            self.put(
                "profile.preferred_language",
                str(profile["preferred_language"]),
                memory_type=MemoryType.PREFERENCE,
                scope=MemoryScope.USER,
                scope_id=scope_id,
                provenance=provenance,
            )
            imported += 1
        for index, pref in enumerate(profile.get("preferences") or []):
            self.put(
                f"profile.preference.{index}",
                str(pref),
                memory_type=MemoryType.PREFERENCE,
                scope=MemoryScope.USER,
                scope_id=scope_id,
                provenance=provenance,
            )
            imported += 1
        for index, fact in enumerate(profile.get("facts") or []):
            self.put(
                f"profile.fact.{index}",
                str(fact),
                memory_type=MemoryType.FACT,
                scope=MemoryScope.USER,
                scope_id=scope_id,
                provenance=provenance,
            )
            imported += 1
        memories = payload.get("memories") if isinstance(payload.get("memories"), dict) else {}
        for key, item in memories.items():
            if not isinstance(item, dict) or not str(item.get("value") or "").strip():
                continue
            category = str(item.get("category") or "general")
            self.put(
                str(key),
                str(item["value"]),
                memory_type=MemoryType.FACT,
                scope=MemoryScope.USER,
                scope_id=scope_id,
                provenance=f"{provenance}:{category}",
                explicit=True,
            )
            imported += 1
        with self._lock, self._conn:
            self._conn.execute(
                "INSERT INTO migration_log(migration_id,source,source_checksum,imported_count,created_at) VALUES(?,?,?,?,?)",
                (f"mig_{uuid.uuid4().hex}", str(source.resolve()), checksum, imported, time.time()),
            )
        return {"status": "imported", "imported": imported, "checksum": checksum}

    def health(self) -> dict[str, Any]:
        with self._lock:
            integrity = self._conn.execute("PRAGMA integrity_check").fetchone()[0]
            active = self._conn.execute(
                "SELECT COUNT(*) FROM memories WHERE deleted_at IS NULL"
            ).fetchone()[0]
            deleted = self._conn.execute(
                "SELECT COUNT(*) FROM memories WHERE deleted_at IS NOT NULL"
            ).fetchone()[0]
        return {"integrity": integrity, "active": int(active), "deleted": int(deleted)}