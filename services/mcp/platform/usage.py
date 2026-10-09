"""Idempotent usage ledger and hard budget checks for agent turns."""
from __future__ import annotations

import calendar
import hashlib
import json
import re
import sqlite3
import threading
import time
import uuid
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterator


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


class UsageError(RuntimeError):
    """Base usage accounting error."""


class UsageLimitExceeded(UsageError):
    """Raised before a usage record would exceed a hard budget."""


class UsageConflict(UsageError):
    """Raised when an idempotency key is reused with different usage."""


@dataclass(frozen=True)
class UsageBudget:
    prompt_tokens: int | None = None
    completion_tokens: int | None = None
    tool_calls: int | None = None
    cpu_milliseconds: int | None = None
    gpu_milliseconds: int | None = None
    vram_byte_seconds: int | None = None
    network_bytes: int | None = None
    artifact_bytes: int | None = None
    external_cost_micros: int | None = None

    def __post_init__(self) -> None:
        for field_name in self.__dataclass_fields__:
            value = getattr(self, field_name)
            if value is not None and (isinstance(value, bool) or int(value) < 0):
                raise ValueError(f"{field_name} must be a non-negative integer or None")


@dataclass(frozen=True)
class UsageDelta:
    session_id: str
    turn_id: str
    principal_id: str = ""
    node_id: str = ""
    model_id: str = ""
    prompt_tokens: int = 0
    completion_tokens: int = 0
    tool_calls: int = 0
    cpu_milliseconds: int = 0
    gpu_milliseconds: int = 0
    vram_byte_seconds: int = 0
    network_bytes: int = 0
    artifact_bytes: int = 0
    external_cost_micros: int = 0
    tenant_id: str = ""
    execution_job_ids: tuple[str, ...] = ()
    execution_node_ids: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not re.fullmatch(r"[A-Za-z0-9_.:-]{1,160}", str(self.session_id)) or not re.fullmatch(r"[A-Za-z0-9_.:-]{1,160}", str(self.turn_id)):
            raise ValueError("invalid session/turn id")
        for name in ("prompt_tokens", "completion_tokens", "tool_calls", "cpu_milliseconds", "gpu_milliseconds", "vram_byte_seconds", "network_bytes", "artifact_bytes", "external_cost_micros"):
            if int(getattr(self, name)) < 0:
                raise ValueError(f"{name} must be non-negative")
        for name in ("principal_id", "node_id", "model_id", "tenant_id"):
            value = str(getattr(self, name) or "")
            if len(value) > 160:
                raise ValueError(f"{name} is too long")
        for name in ("execution_job_ids", "execution_node_ids"):
            values = getattr(self, name)
            if not isinstance(values, (tuple, list)) or len(values) > 32:
                raise ValueError(f"{name} must contain at most 32 identifiers")
            for value in values:
                if not isinstance(value, str) or not 1 <= len(value.strip()) <= 160:
                    raise ValueError(f"{name} contains an invalid identifier")


@dataclass(frozen=True)
class UsageRecord:
    usage_id: str
    idempotency_key: str
    recorded_at: float
    delta: UsageDelta


@dataclass(frozen=True)
class UsageTotals:
    prompt_tokens: int = 0
    completion_tokens: int = 0
    tool_calls: int = 0
    cpu_milliseconds: int = 0
    gpu_milliseconds: int = 0
    vram_byte_seconds: int = 0
    network_bytes: int = 0
    artifact_bytes: int = 0
    external_cost_micros: int = 0


@dataclass(frozen=True)
class UsageQuota:
    """Hard aggregate quota for one durable usage scope and UTC period."""

    scope_type: str
    scope_id: str
    period: str
    budget: UsageBudget

    def __post_init__(self) -> None:
        if self.scope_type not in {"global", "tenant", "principal", "session"}:
            raise ValueError("unsupported usage quota scope")
        if self.scope_type == "global":
            if str(self.scope_id) not in {"", "global"}:
                raise ValueError("global usage quota must use an empty or global scope_id")
        elif not str(self.scope_id or "").strip():
            raise ValueError("scoped usage quota requires a scope_id")
        if self.period not in {"lifetime", "daily", "monthly"}:
            raise ValueError("unsupported usage quota period")
        if not isinstance(self.budget, UsageBudget):
            raise TypeError("usage quota budget must be a UsageBudget")


class UsageLedger:
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
                """CREATE TABLE IF NOT EXISTS usage_records (
                    usage_id TEXT PRIMARY KEY,
                    idempotency_key TEXT UNIQUE NOT NULL,
                    recorded_at REAL NOT NULL,
                    session_id TEXT NOT NULL,
                    turn_id TEXT NOT NULL,
                    principal_id TEXT NOT NULL,
                    tenant_id TEXT NOT NULL DEFAULT '',
                    node_id TEXT NOT NULL,
                    model_id TEXT NOT NULL,
                    prompt_tokens INTEGER NOT NULL,
                    completion_tokens INTEGER NOT NULL,
                    tool_calls INTEGER NOT NULL,
                    cpu_milliseconds INTEGER NOT NULL,
                    gpu_milliseconds INTEGER NOT NULL,
                    vram_byte_seconds INTEGER NOT NULL,
                    network_bytes INTEGER NOT NULL,
                    artifact_bytes INTEGER NOT NULL,
                    external_cost_micros INTEGER NOT NULL,
                    execution_job_ids_json TEXT NOT NULL DEFAULT '[]',
                    execution_node_ids_json TEXT NOT NULL DEFAULT '[]',
                    fingerprint TEXT NOT NULL
                )"""
            )
            connection.execute("CREATE INDEX IF NOT EXISTS usage_session_idx ON usage_records(session_id, recorded_at)")
            connection.execute("CREATE INDEX IF NOT EXISTS usage_principal_idx ON usage_records(principal_id, recorded_at)")
            connection.execute(
                """CREATE TABLE IF NOT EXISTS usage_quotas (
                    scope_type TEXT NOT NULL,
                    scope_id TEXT NOT NULL,
                    period TEXT NOT NULL,
                    budget_json TEXT NOT NULL,
                    updated_at REAL NOT NULL,
                    PRIMARY KEY(scope_type, scope_id, period)
                )"""
            )
            columns = {
                str(row["name"])
                for row in connection.execute("PRAGMA table_info(usage_records)").fetchall()
            }
            if "tenant_id" not in columns:
                connection.execute(
                    "ALTER TABLE usage_records ADD COLUMN tenant_id TEXT NOT NULL DEFAULT ''"
                )
            if "execution_job_ids_json" not in columns:
                connection.execute(
                    "ALTER TABLE usage_records ADD COLUMN execution_job_ids_json TEXT NOT NULL DEFAULT '[]'"
                )
            if "execution_node_ids_json" not in columns:
                connection.execute(
                    "ALTER TABLE usage_records ADD COLUMN execution_node_ids_json TEXT NOT NULL DEFAULT '[]'"
                )
            connection.execute("CREATE INDEX IF NOT EXISTS usage_tenant_idx ON usage_records(tenant_id, recorded_at)")

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
    def _fingerprint(delta: UsageDelta) -> str:
        return hashlib.sha256(json.dumps(delta.__dict__, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()

    @staticmethod
    def _budget_dict(budget: UsageBudget) -> dict[str, int | None]:
        return {name: getattr(budget, name) for name in UsageBudget.__dataclass_fields__}

    @staticmethod
    def _period_start(period: str, now: float) -> float:
        if period == "lifetime":
            return 0.0
        current = time.gmtime(float(now))
        if period == "daily":
            return float(calendar.timegm((current.tm_year, current.tm_mon, current.tm_mday, 0, 0, 0)))
        if period == "monthly":
            return float(calendar.timegm((current.tm_year, current.tm_mon, 1, 0, 0, 0)))
        raise ValueError("unsupported usage quota period")

    @classmethod
    def _quota_budget(cls, row: sqlite3.Row) -> UsageBudget:
        values = json.loads(str(row["budget_json"]))
        return UsageBudget(**{name: values.get(name) for name in UsageBudget.__dataclass_fields__})

    def set_quota(self, quota: UsageQuota) -> UsageQuota:
        """Create or replace an operator-configured hard quota."""
        if not isinstance(quota, UsageQuota):
            raise TypeError("quota must be a UsageQuota")
        scope_id = "global" if quota.scope_type == "global" else str(quota.scope_id).strip()
        with self._transaction() as connection:
            connection.execute(
                """INSERT INTO usage_quotas(scope_type, scope_id, period, budget_json, updated_at)
                   VALUES (?, ?, ?, ?, ?)
                   ON CONFLICT(scope_type, scope_id, period) DO UPDATE SET
                       budget_json = excluded.budget_json,
                       updated_at = excluded.updated_at""",
                (quota.scope_type, scope_id, quota.period, _json(self._budget_dict(quota.budget)), time.time()),
            )
        return UsageQuota(quota.scope_type, scope_id, quota.period, quota.budget)

    def list_quotas(self) -> tuple[UsageQuota, ...]:
        with self._lock:
            rows = self._connection.execute(
                "SELECT * FROM usage_quotas ORDER BY scope_type, scope_id, period"
            ).fetchall()
        return tuple(
            UsageQuota(
                str(row["scope_type"]),
                str(row["scope_id"]),
                str(row["period"]),
                self._quota_budget(row),
            )
            for row in rows
        )

    def remove_quota(self, *, scope_type: str, scope_id: str = "", period: str) -> bool:
        quota = UsageQuota(scope_type, scope_id, period, UsageBudget())
        normalized_id = "global" if quota.scope_type == "global" else str(quota.scope_id).strip()
        with self._transaction() as connection:
            result = connection.execute(
                "DELETE FROM usage_quotas WHERE scope_type = ? AND scope_id = ? AND period = ?",
                (quota.scope_type, normalized_id, quota.period),
            )
        return result.rowcount == 1

    def totals(
        self,
        *,
        session_id: str | None = None,
        principal_id: str | None = None,
        tenant_id: str | None = None,
        since: float | None = None,
        until: float | None = None,
    ) -> UsageTotals:
        where: list[str] = []
        params: list[Any] = []
        if session_id is not None:
            where.append("session_id = ?")
            params.append(str(session_id))
        if principal_id is not None:
            where.append("principal_id = ?")
            params.append(str(principal_id))
        if tenant_id is not None:
            where.append("tenant_id = ?")
            params.append(str(tenant_id))
        if since is not None:
            where.append("recorded_at >= ?")
            params.append(float(since))
        if until is not None:
            where.append("recorded_at < ?")
            params.append(float(until))
        query = "SELECT COALESCE(SUM(prompt_tokens),0) prompt_tokens, COALESCE(SUM(completion_tokens),0) completion_tokens, COALESCE(SUM(tool_calls),0) tool_calls, COALESCE(SUM(cpu_milliseconds),0) cpu_milliseconds, COALESCE(SUM(gpu_milliseconds),0) gpu_milliseconds, COALESCE(SUM(vram_byte_seconds),0) vram_byte_seconds, COALESCE(SUM(network_bytes),0) network_bytes, COALESCE(SUM(artifact_bytes),0) artifact_bytes, COALESCE(SUM(external_cost_micros),0) external_cost_micros FROM usage_records"
        if where:
            query += " WHERE " + " AND ".join(where)
        with self._lock:
            row = self._connection.execute(query, params).fetchone()
        return UsageTotals(**{name: int(row[name]) for name in UsageTotals.__dataclass_fields__})

    @staticmethod
    def _check_budget(totals: UsageTotals, delta: UsageDelta, budget: UsageBudget | None, *, label: str = "usage budget") -> None:
        if budget is None:
            return
        checks = {
            "prompt_tokens": budget.prompt_tokens,
            "completion_tokens": budget.completion_tokens,
            "tool_calls": budget.tool_calls,
            "cpu_milliseconds": budget.cpu_milliseconds,
            "gpu_milliseconds": budget.gpu_milliseconds,
            "vram_byte_seconds": budget.vram_byte_seconds,
            "network_bytes": budget.network_bytes,
            "artifact_bytes": budget.artifact_bytes,
            "external_cost_micros": budget.external_cost_micros,
        }
        for field_name, limit in checks.items():
            if limit is not None and int(getattr(totals, field_name)) + int(getattr(delta, field_name)) > int(limit):
                raise UsageLimitExceeded(f"{label} exceeded: {field_name}")

    def _check_quotas(self, connection: sqlite3.Connection, delta: UsageDelta, *, now: float) -> None:
        scopes = [("global", "global"), ("session", str(delta.session_id))]
        if delta.principal_id:
            scopes.append(("principal", str(delta.principal_id)))
        if delta.tenant_id:
            scopes.append(("tenant", str(delta.tenant_id)))
        for scope_type, scope_id in scopes:
            rows = connection.execute(
                "SELECT * FROM usage_quotas WHERE scope_type = ? AND scope_id = ?",
                (scope_type, scope_id),
            ).fetchall()
            for row in rows:
                period = str(row["period"])
                start = self._period_start(period, now)
                where = ["recorded_at >= ?"]
                params: list[Any] = [start]
                if scope_type == "session":
                    where.append("session_id = ?")
                    params.append(scope_id)
                elif scope_type == "principal":
                    where.append("principal_id = ?")
                    params.append(scope_id)
                elif scope_type == "tenant":
                    where.append("tenant_id = ?")
                    params.append(scope_id)
                totals_row = connection.execute(
                    "SELECT "
                    + ", ".join(
                        f"COALESCE(SUM({name}), 0) AS {name}"
                        for name in UsageTotals.__dataclass_fields__
                    )
                    + " FROM usage_records WHERE "
                    + " AND ".join(where),
                    params,
                ).fetchone()
                totals = UsageTotals(**{
                    name: int(totals_row[name])
                    for name in UsageTotals.__dataclass_fields__
                })
                self._check_budget(
                    totals,
                    delta,
                    self._quota_budget(row),
                    label=f"{scope_type} {scope_id} {period} quota",
                )

    def record(self, delta: UsageDelta, *, idempotency_key: str | None = None, budget: UsageBudget | None = None) -> UsageRecord:
        key = str(idempotency_key or f"usage_{uuid.uuid4().hex}")
        if not re.fullmatch(r"[A-Za-z0-9_.:-]{1,200}", key):
            raise ValueError("invalid usage idempotency key")
        fingerprint = self._fingerprint(delta)
        with self._transaction() as connection:
            existing = connection.execute("SELECT * FROM usage_records WHERE idempotency_key = ?", (key,)).fetchone()
            if existing is not None:
                if str(existing["fingerprint"]) != fingerprint:
                    raise UsageConflict("usage idempotency key was reused with different data")
                return self._record(existing)
            totals = self.totals(session_id=delta.session_id)
            self._check_budget(totals, delta, budget)
            now = time.time()
            self._check_quotas(connection, delta, now=now)
            usage_id = f"usage_{uuid.uuid4().hex}"
            values = [usage_id, key, now, delta.session_id, delta.turn_id, delta.principal_id, delta.tenant_id, delta.node_id, delta.model_id, delta.prompt_tokens, delta.completion_tokens, delta.tool_calls, delta.cpu_milliseconds, delta.gpu_milliseconds, delta.vram_byte_seconds, delta.network_bytes, delta.artifact_bytes, delta.external_cost_micros, _json(list(delta.execution_job_ids)), _json(list(delta.execution_node_ids)), fingerprint]
            connection.execute("INSERT INTO usage_records (usage_id, idempotency_key, recorded_at, session_id, turn_id, principal_id, tenant_id, node_id, model_id, prompt_tokens, completion_tokens, tool_calls, cpu_milliseconds, gpu_milliseconds, vram_byte_seconds, network_bytes, artifact_bytes, external_cost_micros, execution_job_ids_json, execution_node_ids_json, fingerprint) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", values)
            return self._record(connection.execute("SELECT * FROM usage_records WHERE usage_id = ?", (usage_id,)).fetchone())

    @staticmethod
    def _record(row: sqlite3.Row) -> UsageRecord:
        def _ids(column: str) -> tuple[str, ...]:
            try:
                raw = json.loads(str(row[column]))
            except (KeyError, TypeError, ValueError):
                return ()
            return tuple(value for value in raw if isinstance(value, str)) if isinstance(raw, list) else ()

        delta = UsageDelta(
            session_id=str(row["session_id"]), turn_id=str(row["turn_id"]), principal_id=str(row["principal_id"]), tenant_id=str(row["tenant_id"]), node_id=str(row["node_id"]), model_id=str(row["model_id"]), prompt_tokens=int(row["prompt_tokens"]), completion_tokens=int(row["completion_tokens"]), tool_calls=int(row["tool_calls"]), cpu_milliseconds=int(row["cpu_milliseconds"]), gpu_milliseconds=int(row["gpu_milliseconds"]), vram_byte_seconds=int(row["vram_byte_seconds"]), network_bytes=int(row["network_bytes"]), artifact_bytes=int(row["artifact_bytes"]), external_cost_micros=int(row["external_cost_micros"]), execution_job_ids=_ids("execution_job_ids_json"), execution_node_ids=_ids("execution_node_ids_json")
        )
        return UsageRecord(str(row["usage_id"]), str(row["idempotency_key"]), float(row["recorded_at"]), delta)

    def close(self) -> None:
        with self._lock:
            self._connection.close()

    def __enter__(self) -> "UsageLedger":
        return self

    def __exit__(self, *exc: Any) -> None:
        self.close()
