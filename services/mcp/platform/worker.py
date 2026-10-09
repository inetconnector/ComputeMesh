"""Durable worker pickup for queued and explicitly resumed agent turns.

The worker is intentionally provider-neutral. A deployment supplies a model
caller and a policy-bound harness factory; this module only claims durable
turns, passes the exact approved action IDs to the broker, and records worker
failures without inventing a fallback execution path.
"""
from __future__ import annotations

import secrets
import sqlite3
import threading
import time
import uuid
from collections import deque
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Deque

from .harness import HarnessRun, MeshAgentHarness
from .session import (
    AgentSession,
    AgentSessionStore,
    AgentTurn,
    ApprovalStatus,
    SessionStateConflict,
    TurnStatus,
)
from .usage import UsageBudget


class AgentWorkerError(RuntimeError):
    """Raised when a worker request is malformed or cannot be resolved."""


WorkerPreflight = Callable[[AgentSession, AgentTurn], bool]


@dataclass(frozen=True)
class WorkerConcurrencyBudget:
    """In-process admission limits for parallel durable turns."""

    global_limit: int = 32
    principal_limit: int = 4
    session_limit: int = 1
    tenant_limit: int | None = None

    def __post_init__(self) -> None:
        for field in ("global_limit", "principal_limit", "session_limit"):
            value = getattr(self, field)
            if isinstance(value, bool) or not 1 <= int(value) <= 10_000:
                raise ValueError(f"{field} must be between 1 and 10000")
        if self.tenant_limit is not None and (
            isinstance(self.tenant_limit, bool) or not 1 <= int(self.tenant_limit) <= 10_000
        ):
            raise ValueError("tenant_limit must be between 1 and 10000 or None")


@dataclass(frozen=True)
class WorkerSchedulingPolicy:
    """Durable queue policy shared by workers in one deployment.

    Priority is persisted on each turn. Aging raises the effective priority
    of old work in bounded steps, while principal fairness rotates equal-score
    candidates so one producer cannot monopolize a busy worker pool.
    """

    fair_principals: bool = True
    aging_interval_seconds: float = 60.0
    max_candidates: int = 500

    def __post_init__(self) -> None:
        if not isinstance(self.fair_principals, bool):
            raise ValueError("fair_principals must be a boolean")
        try:
            aging = float(self.aging_interval_seconds)
            candidates = int(self.max_candidates)
        except (TypeError, ValueError) as exc:
            raise ValueError("invalid worker scheduling policy") from exc
        if not 1.0 <= aging <= 86_400.0:
            raise ValueError("aging_interval_seconds must be between 1 and 86400")
        if not 1 <= candidates <= 5_000:
            raise ValueError("max_candidates must be between 1 and 5000")


class WorkerConcurrencyGate:
    """Thread-safe admission gate shared by a supervised worker pool."""

    def __init__(self, budget: WorkerConcurrencyBudget | None = None) -> None:
        self.budget = budget or WorkerConcurrencyBudget()
        self._lock = threading.RLock()
        self._active_global = 0
        self._active_principals: dict[str, int] = {}
        self._active_sessions: dict[str, int] = {}
        self._active_tenants: dict[str, int] = {}
        self._admissions: dict[str, tuple[str, str, str]] = {}

    def try_acquire(
        self,
        *,
        principal_id: str,
        session_id: str,
        admission_key: str | None = None,
        tenant_id: str = "",
    ) -> bool:
        principal = str(principal_id or "")
        session = str(session_id or "")
        tenant = str(tenant_id or "")
        if not principal or not session:
            raise ValueError("principal_id and session_id are required")
        if len(tenant) > 160:
            raise ValueError("tenant_id is too long")
        with self._lock:
            if admission_key:
                existing = self._admissions.get(str(admission_key))
                if existing is not None:
                    return existing == (principal, session, tenant)
            if self._active_global >= self.budget.global_limit:
                return False
            if self._active_principals.get(principal, 0) >= self.budget.principal_limit:
                return False
            if self._active_sessions.get(session, 0) >= self.budget.session_limit:
                return False
            if (
                tenant
                and self.budget.tenant_limit is not None
                and self._active_tenants.get(tenant, 0) >= self.budget.tenant_limit
            ):
                return False
            self._active_global += 1
            self._active_principals[principal] = self._active_principals.get(principal, 0) + 1
            self._active_sessions[session] = self._active_sessions.get(session, 0) + 1
            if tenant:
                self._active_tenants[tenant] = self._active_tenants.get(tenant, 0) + 1
            if admission_key:
                self._admissions[str(admission_key)] = (principal, session, tenant)
            return True

    def release(
        self,
        *,
        principal_id: str,
        session_id: str,
        admission_key: str | None = None,
        tenant_id: str = "",
    ) -> None:
        principal = str(principal_id or "")
        session = str(session_id or "")
        tenant = str(tenant_id or "")
        with self._lock:
            if admission_key:
                existing = self._admissions.get(str(admission_key))
                if existing is not None:
                    if existing[:2] != (principal, session):
                        raise AgentWorkerError("worker concurrency release does not match its admission")
                    if not tenant:
                        tenant = existing[2]
                    elif tenant != existing[2]:
                        raise AgentWorkerError("worker concurrency release tenant does not match its admission")
            if self._active_global <= 0 or self._active_principals.get(principal, 0) <= 0 or self._active_sessions.get(session, 0) <= 0:
                raise AgentWorkerError("worker concurrency release has no matching admission")
            if tenant and self._active_tenants.get(tenant, 0) <= 0:
                raise AgentWorkerError("worker tenant concurrency release has no matching admission")
            self._active_global -= 1
            self._active_principals[principal] -= 1
            self._active_sessions[session] -= 1
            if self._active_principals[principal] == 0:
                del self._active_principals[principal]
            if self._active_sessions[session] == 0:
                del self._active_sessions[session]
            if tenant:
                self._active_tenants[tenant] -= 1
                if self._active_tenants[tenant] == 0:
                    del self._active_tenants[tenant]
            if admission_key:
                self._admissions.pop(str(admission_key), None)

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            return {
                "active_global": self._active_global,
                "active_principals": dict(self._active_principals),
                "active_sessions": dict(self._active_sessions),
                "active_tenants": dict(self._active_tenants),
                "budget": {
                    "global_limit": self.budget.global_limit,
                    "principal_limit": self.budget.principal_limit,
                    "session_limit": self.budget.session_limit,
                    "tenant_limit": self.budget.tenant_limit,
                },
            }


class DurableWorkerConcurrencyGate:
    """SQLite-backed admission leases shared by worker processes.

    The gate intentionally stores only scheduling metadata. It does not become
    a second source of truth for turn state: the session store still claims
    turns atomically after admission. Expired rows are reclaimed on every
    mutating/read operation so a crashed worker cannot hold capacity forever.
    """

    def __init__(
        self,
        path: str | Path,
        budget: WorkerConcurrencyBudget | None = None,
        *,
        lease_seconds: float = 300.0,
        clock: Callable[[], float] = time.time,
    ) -> None:
        if str(path) == ":memory:":
            raise ValueError("durable worker concurrency requires a filesystem database")
        try:
            lease = float(lease_seconds)
        except (TypeError, ValueError) as exc:
            raise ValueError("lease_seconds must be a positive number") from exc
        if not 1.0 <= lease <= 86_400.0:
            raise ValueError("lease_seconds must be between 1 and 86400")
        if not callable(clock):
            raise TypeError("clock must be callable")
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.budget = budget or WorkerConcurrencyBudget()
        self.lease_seconds = lease
        self._clock = clock
        self._lock = threading.RLock()
        self._connection = sqlite3.connect(
            str(self.path),
            check_same_thread=False,
            timeout=30.0,
        )
        self._connection.row_factory = sqlite3.Row
        self._connection.execute("PRAGMA busy_timeout = 30000")
        self._connection.execute("PRAGMA journal_mode = WAL")
        self._connection.execute("PRAGMA synchronous = NORMAL")
        with self._transaction() as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS agent_worker_admissions (
                    admission_id TEXT PRIMARY KEY,
                    admission_key TEXT NOT NULL,
                    worker_id TEXT NOT NULL,
                    principal_id TEXT NOT NULL,
                    session_id TEXT NOT NULL,
                    tenant_id TEXT NOT NULL DEFAULT '',
                    acquired_at REAL NOT NULL,
                    heartbeat_at REAL NOT NULL,
                    expires_at REAL NOT NULL,
                    released_at REAL
                )
                """
            )
            connection.execute(
                """
                CREATE INDEX IF NOT EXISTS agent_worker_admissions_active_idx
                ON agent_worker_admissions(released_at, expires_at)
                """
            )
            connection.execute(
                """
                CREATE INDEX IF NOT EXISTS agent_worker_admissions_principal_idx
                ON agent_worker_admissions(principal_id, released_at, expires_at)
                """
            )
            columns = {
                str(row["name"])
                for row in connection.execute("PRAGMA table_info(agent_worker_admissions)").fetchall()
            }
            if "tenant_id" not in columns:
                connection.execute(
                    "ALTER TABLE agent_worker_admissions ADD COLUMN tenant_id TEXT NOT NULL DEFAULT ''"
                )
            connection.execute(
                """
                CREATE INDEX IF NOT EXISTS agent_worker_admissions_session_idx
                ON agent_worker_admissions(session_id, released_at, expires_at)
                """
            )
            connection.execute(
                """
                CREATE INDEX IF NOT EXISTS agent_worker_admissions_tenant_idx
                ON agent_worker_admissions(tenant_id, released_at, expires_at)
                """
            )

    @contextmanager
    def _transaction(self):
        with self._lock:
            try:
                self._connection.execute("BEGIN IMMEDIATE")
                yield self._connection
                self._connection.commit()
            except Exception:
                self._connection.rollback()
                raise

    def _reclaim_expired(self, connection: sqlite3.Connection, now: float) -> None:
        connection.execute(
            "DELETE FROM agent_worker_admissions WHERE released_at IS NULL AND expires_at <= ?",
            (float(now),),
        )

    @staticmethod
    def _validate_ids(principal_id: str, session_id: str, tenant_id: str = "") -> tuple[str, str, str]:
        principal = str(principal_id or "")
        session = str(session_id or "")
        tenant = str(tenant_id or "")
        if not principal or not session:
            raise ValueError("principal_id and session_id are required")
        if len(tenant) > 160:
            raise ValueError("tenant_id is too long")
        return principal, session, tenant

    def try_acquire(
        self,
        *,
        principal_id: str,
        session_id: str,
        admission_key: str | None = None,
        worker_id: str = "",
        tenant_id: str = "",
    ) -> bool:
        principal, session, tenant = self._validate_ids(principal_id, session_id, tenant_id)
        key = str(admission_key or f"{worker_id}:{session}")
        if not key:
            raise ValueError("admission_key or worker_id is required")
        now = float(self._clock())
        with self._transaction() as connection:
            self._reclaim_expired(connection, now)
            existing = connection.execute(
                """
                SELECT admission_id, principal_id, session_id, tenant_id FROM agent_worker_admissions
                WHERE admission_key = ? AND released_at IS NULL
                """,
                (key,),
            ).fetchone()
            if existing is not None:
                if (
                    str(existing["principal_id"]) != principal
                    or str(existing["session_id"]) != session
                    or str(existing["tenant_id"]) != tenant
                ):
                    return False
                connection.execute(
                    """
                    UPDATE agent_worker_admissions
                    SET heartbeat_at = ?, expires_at = ?
                    WHERE admission_id = ?
                    """,
                    (now, now + self.lease_seconds, str(existing["admission_id"])),
                )
                return True
            global_count = int(connection.execute(
                "SELECT COUNT(*) FROM agent_worker_admissions WHERE released_at IS NULL",
            ).fetchone()[0])
            principal_count = int(connection.execute(
                """
                SELECT COUNT(*) FROM agent_worker_admissions
                WHERE released_at IS NULL AND principal_id = ?
                """,
                (principal,),
            ).fetchone()[0])
            session_count = int(connection.execute(
                """
                SELECT COUNT(*) FROM agent_worker_admissions
                WHERE released_at IS NULL AND session_id = ?
                """,
                (session,),
            ).fetchone()[0])
            tenant_count = 0
            if tenant and self.budget.tenant_limit is not None:
                tenant_count = int(connection.execute(
                    """
                    SELECT COUNT(*) FROM agent_worker_admissions
                    WHERE released_at IS NULL AND tenant_id = ?
                    """,
                    (tenant,),
                ).fetchone()[0])
            if (
                global_count >= self.budget.global_limit
                or principal_count >= self.budget.principal_limit
                or session_count >= self.budget.session_limit
                or (
                    tenant
                    and self.budget.tenant_limit is not None
                    and tenant_count >= self.budget.tenant_limit
                )
            ):
                return False
            connection.execute(
                """
                INSERT INTO agent_worker_admissions(
                    admission_id, admission_key, worker_id, principal_id,
                    session_id, tenant_id, acquired_at, heartbeat_at, expires_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    f"admission_{uuid.uuid4().hex}",
                    key,
                    str(worker_id or ""),
                    principal,
                    session,
                    tenant,
                    now,
                    now,
                    now + self.lease_seconds,
                ),
            )
            return True

    def renew(self, *, admission_key: str) -> bool:
        key = str(admission_key or "")
        if not key:
            raise ValueError("admission_key is required")
        now = float(self._clock())
        with self._transaction() as connection:
            self._reclaim_expired(connection, now)
            result = connection.execute(
                """
                UPDATE agent_worker_admissions
                SET heartbeat_at = ?, expires_at = ?
                WHERE admission_key = ? AND released_at IS NULL
                """,
                (now, now + self.lease_seconds, key),
            )
            return result.rowcount == 1

    def release(
        self,
        *,
        principal_id: str,
        session_id: str,
        admission_key: str | None = None,
        tenant_id: str = "",
    ) -> None:
        principal, session, tenant = self._validate_ids(principal_id, session_id, tenant_id)
        with self._transaction() as connection:
            if admission_key:
                result = connection.execute(
                    """
                    UPDATE agent_worker_admissions
                    SET released_at = ?
                    WHERE admission_key = ? AND principal_id = ? AND session_id = ?
                      AND (? = '' OR tenant_id = ?)
                      AND released_at IS NULL
                    """,
                    (float(self._clock()), str(admission_key), principal, session, tenant, tenant),
                )
            else:
                result = connection.execute(
                    """
                    UPDATE agent_worker_admissions
                    SET released_at = ?
                    WHERE admission_id = (
                        SELECT admission_id FROM agent_worker_admissions
                        WHERE principal_id = ? AND session_id = ? AND released_at IS NULL
                          AND (? = '' OR tenant_id = ?)
                        ORDER BY acquired_at DESC LIMIT 1
                    )
                    """,
                    (float(self._clock()), principal, session, tenant, tenant),
                )
            if result.rowcount != 1:
                raise AgentWorkerError("worker concurrency release has no matching admission")

    def snapshot(self) -> dict[str, Any]:
        now = float(self._clock())
        with self._transaction() as connection:
            self._reclaim_expired(connection, now)
            rows = connection.execute(
                """
                SELECT principal_id, session_id, tenant_id FROM agent_worker_admissions
                WHERE released_at IS NULL
                """
            ).fetchall()
        principals: dict[str, int] = {}
        sessions: dict[str, int] = {}
        tenants: dict[str, int] = {}
        for row in rows:
            principals[str(row["principal_id"])] = principals.get(str(row["principal_id"]), 0) + 1
            sessions[str(row["session_id"])] = sessions.get(str(row["session_id"]), 0) + 1
            if str(row["tenant_id"]):
                tenants[str(row["tenant_id"])] = tenants.get(str(row["tenant_id"]), 0) + 1
        return {
            "active_global": len(rows),
            "active_principals": principals,
            "active_sessions": sessions,
            "active_tenants": tenants,
            "budget": {
                "global_limit": self.budget.global_limit,
                "principal_limit": self.budget.principal_limit,
                "session_limit": self.budget.session_limit,
                "tenant_limit": self.budget.tenant_limit,
            },
        }

    def close(self) -> None:
        with self._lock:
            self._connection.close()


@dataclass(frozen=True)
class AgentWorkerRequest:
    """Validated execution inputs supplied by the deployment resolver."""

    model: str
    llm_caller: Callable[[list[dict[str, Any]], list[dict[str, Any]]], dict[str, Any]]
    is_owner: bool = True
    max_iterations: int | None = None
    principal_id: str = ""
    node_id: str = ""
    usage_budget: UsageBudget | None = None
    tenant_id: str = ""
    # Optional deployment-owned resource/billing lifecycle. The core worker
    # never interprets the reservation token or performs financial actions.
    billing_reserve: Callable[[AgentSession, AgentTurn], Any] | None = None
    billing_settle: Callable[[Any, HarnessRun], None] | None = None
    billing_release: Callable[[Any, BaseException], None] | None = None

    def validate(self) -> None:
        model = str(self.model or "").strip()
        if not 1 <= len(model) <= 256:
            raise AgentWorkerError("worker model is required and must be at most 256 characters")
        if not callable(self.llm_caller):
            raise AgentWorkerError("worker model caller is not callable")
        if self.max_iterations is not None:
            try:
                valid_iterations = 1 <= int(self.max_iterations) <= 20
            except (TypeError, ValueError):
                valid_iterations = False
            if not valid_iterations:
                raise AgentWorkerError("worker max_iterations is outside the supported range")
        if len(str(self.tenant_id or "")) > 160:
            raise AgentWorkerError("worker tenant_id is too long")
        hooks = (self.billing_reserve, self.billing_settle, self.billing_release)
        if any(hook is not None for hook in hooks) and not all(callable(hook) for hook in hooks):
            raise AgentWorkerError("worker billing lifecycle requires reserve, settle and release hooks")


@dataclass(frozen=True)
class AgentWorkerResult:
    turn_id: str
    status: TurnStatus
    claimed: bool
    execution: HarnessRun | None = None
    error_type: str = ""


@dataclass(frozen=True)
class AgentWorkerServiceSnapshot:
    """Bounded operational view of a supervised worker service."""

    running: bool
    worker_ids: tuple[str, ...]
    recovered_turn_ids: tuple[str, ...]
    result_count: int
    error_count: int
    errors: tuple[str, ...]


class MeshAgentWorkerService:
    """Supervise one or more durable workers in a process.

    Startup recovery pauses turns that were active in a previous process. It
    never replays them implicitly; an explicit resume control is still needed
    before the normal queue can claim them. Worker results and service errors
    are retained in bounded memory so a long-running node cannot grow without
    limit merely because an operator is not watching it.
    """

    def __init__(
        self,
        session_store: AgentSessionStore,
        *,
        worker_factory: Callable[[str], "MeshAgentWorker"],
        worker_count: int = 1,
        worker_prefix: str = "mesh-agent",
        poll_interval: float = 0.25,
        batch_limit: int = 1,
        max_results: int = 1000,
        recover_on_start: bool = True,
        concurrency_budget: WorkerConcurrencyBudget | None = None,
        concurrency_gate: Any | None = None,
        persistent_concurrency: bool = False,
        concurrency_lease_seconds: float = 300.0,
    ) -> None:
        if not callable(worker_factory):
            raise TypeError("worker_factory must be callable")
        try:
            count = int(worker_count)
            result_limit = int(max_results)
        except (TypeError, ValueError) as exc:
            raise ValueError("worker_count and max_results must be integers") from exc
        if not 1 <= count <= 32:
            raise ValueError("worker_count must be between 1 and 32")
        if not 1 <= result_limit <= 10000:
            raise ValueError("max_results must be between 1 and 10000")
        prefix = str(worker_prefix or "").strip()
        if not prefix or len(prefix) > 96:
            raise ValueError("worker_prefix is required and must be at most 96 characters")
        self.session_store = session_store
        self.poll_interval = min(max(float(poll_interval), 0.01), 60.0)
        self.batch_limit = max(1, min(int(batch_limit), 100))
        self.workers = tuple(
            worker_factory(prefix if count == 1 else f"{prefix}_{index + 1}")
            for index in range(count)
        )
        if any(worker.session_store is not session_store for worker in self.workers):
            raise ValueError("all workers must use the service session store")
        self._recover_on_start = bool(recover_on_start)
        self._recovered_turn_ids: tuple[str, ...] = ()
        self._results: Deque[AgentWorkerResult] = deque(maxlen=result_limit)
        self._errors: Deque[str] = deque(maxlen=result_limit)
        self._stop_event = threading.Event()
        self._threads: list[threading.Thread] = []
        self._lock = threading.RLock()
        self._started = False
        if concurrency_gate is not None and (concurrency_budget is not None or persistent_concurrency):
            raise ValueError("provide either concurrency_gate or concurrency_budget/persistent_concurrency")
        if concurrency_gate is not None:
            self.concurrency_gate = concurrency_gate
            self._owns_concurrency_gate = False
        elif persistent_concurrency:
            self.concurrency_gate = DurableWorkerConcurrencyGate(
                session_store.path,
                concurrency_budget,
                lease_seconds=concurrency_lease_seconds,
            )
            self._owns_concurrency_gate = True
        else:
            self.concurrency_gate = WorkerConcurrencyGate(concurrency_budget) if concurrency_budget is not None else None
            self._owns_concurrency_gate = self.concurrency_gate is not None
        if self.concurrency_gate is not None:
            for worker in self.workers:
                worker.set_concurrency_gate(self.concurrency_gate)

    def _run_worker(self, worker: "MeshAgentWorker") -> None:
        try:
            results = worker.run_until_stopped(
                self._stop_event,
                limit=self.batch_limit,
                poll_interval=self.poll_interval,
            )
            with self._lock:
                self._results.extend(results)
        except Exception as exc:
            with self._lock:
                self._errors.append(f"{worker.worker_id}:{type(exc).__name__}")

    def start(self) -> AgentWorkerServiceSnapshot:
        """Start supervised workers; repeated calls while running are safe."""
        with self._lock:
            if any(thread.is_alive() for thread in self._threads):
                return self.snapshot()
            if self._recover_on_start and not self._started:
                self._recovered_turn_ids = tuple(self.session_store.recover_interrupted())
            self._started = True
            self._stop_event.clear()
            self._threads = [
                threading.Thread(
                    target=self._run_worker,
                    args=(worker,),
                    name=f"ComputeMesh-{worker.worker_id}",
                    daemon=True,
                )
                for worker in self.workers
            ]
            for thread in self._threads:
                thread.start()
            return self.snapshot()

    def stop(self) -> None:
        """Request cooperative shutdown of every worker."""
        self._stop_event.set()

    def join(self, timeout: float | None = None) -> bool:
        """Wait for workers and return whether all of them stopped."""
        deadline = None if timeout is None else time.monotonic() + max(0.0, float(timeout))
        for thread in tuple(self._threads):
            remaining = None if deadline is None else max(0.0, deadline - time.monotonic())
            thread.join(remaining)
        return not any(thread.is_alive() for thread in self._threads)

    def close(self, timeout: float | None = 5.0) -> bool:
        """Stop and join the service for process shutdown hooks."""
        self.stop()
        stopped = self.join(timeout)
        if stopped and self._owns_concurrency_gate:
            close = getattr(self.concurrency_gate, "close", None)
            if callable(close):
                close()
            self._owns_concurrency_gate = False
        return stopped

    def results(self) -> tuple[AgentWorkerResult, ...]:
        with self._lock:
            return tuple(self._results)

    def snapshot(self) -> AgentWorkerServiceSnapshot:
        with self._lock:
            return AgentWorkerServiceSnapshot(
                running=any(thread.is_alive() for thread in self._threads),
                worker_ids=tuple(worker.worker_id for worker in self.workers),
                recovered_turn_ids=self._recovered_turn_ids,
                result_count=len(self._results),
                error_count=len(self._errors),
                errors=tuple(self._errors),
            )


class MeshAgentWorker:
    """Claim and execute durable turns exactly once per worker claim."""

    def __init__(
        self,
        session_store: AgentSessionStore,
        *,
        harness_factory: Callable[[AgentSession, AgentTurn, tuple[str, ...]], MeshAgentHarness],
        request_resolver: Callable[[AgentSession, AgentTurn], AgentWorkerRequest],
        worker_id: str | None = None,
        concurrency_gate: Any | None = None,
        scheduling_policy: WorkerSchedulingPolicy | None = None,
        preflight: WorkerPreflight | None = None,
    ) -> None:
        self.session_store = session_store
        self.harness_factory = harness_factory
        self.request_resolver = request_resolver
        self._concurrency_gate = concurrency_gate
        self.scheduling_policy = scheduling_policy or WorkerSchedulingPolicy()
        if preflight is not None and not callable(preflight):
            raise TypeError("preflight must be callable")
        self.preflight = preflight
        self._principal_cursor = 0
        self.worker_id = str(worker_id or f"worker_{secrets.token_hex(8)}")[:128]
        if not self.worker_id:
            raise ValueError("worker_id is required")

    def set_concurrency_gate(self, gate: WorkerConcurrencyGate | None) -> None:
        self._concurrency_gate = gate

    def _approved_ids(self, session_id: str, turn_id: str) -> tuple[str, ...]:
        return tuple(
            approval.approval_id
            for approval in self.session_store.list_approvals(
                session_id=session_id,
                status=ApprovalStatus.APPROVED,
                limit=500,
            )
            if approval.turn_id == str(turn_id)
        )

    def _start_admission_heartbeat(self, admission_key: str) -> tuple[threading.Event, threading.Thread] | None:
        gate = self._concurrency_gate
        renew = getattr(gate, "renew", None) if gate is not None else None
        lease_seconds = getattr(gate, "lease_seconds", None) if gate is not None else None
        if not callable(renew) or lease_seconds is None:
            return None
        interval = max(0.5, min(float(lease_seconds) / 3.0, 30.0))
        stop_event = threading.Event()

        def heartbeat() -> None:
            while not stop_event.wait(interval):
                try:
                    if not bool(renew(admission_key=admission_key)):
                        return
                except Exception:
                    return

        thread = threading.Thread(
            target=heartbeat,
            name=f"ComputeMesh-admission-{self.worker_id}",
            daemon=True,
        )
        thread.start()
        return stop_event, thread

    def _fail_claimed_turn(self, turn: AgentTurn, error: BaseException) -> AgentWorkerResult:
        current = self.session_store.get_turn(turn.turn_id)
        if current.status is TurnStatus.RUNNING:
            try:
                current = self.session_store.transition_turn(
                    turn.turn_id,
                    TurnStatus.FAILED,
                    error=type(error).__name__,
                    reason="worker_failed",
                )
            except SessionStateConflict:
                current = self.session_store.get_turn(turn.turn_id)
        self.session_store.record_event(
            turn.session_id,
            "worker.failed",
            {"turn_id": turn.turn_id, "error_type": type(error).__name__},
            turn_id=turn.turn_id,
        )
        return AgentWorkerResult(
            turn_id=turn.turn_id,
            status=current.status,
            claimed=True,
            error_type=type(error).__name__,
        )

    def _ordered_candidates(self, limit: int) -> list[AgentTurn]:
        """Return a bounded, priority-aware and principal-fair work page."""
        policy = self.scheduling_policy
        candidates = self.session_store.list_turns(
            statuses=(TurnStatus.QUEUED, TurnStatus.RESUMING),
            limit=min(max(limit, policy.max_candidates), 500),
        )
        if self.preflight is not None:
            eligible: list[AgentTurn] = []
            for candidate in candidates:
                session = self.session_store.get_session(candidate.session_id)
                try:
                    ready = bool(self.preflight(session, candidate))
                except Exception as exc:
                    self.session_store.record_event(
                        candidate.session_id,
                        "worker.preflight_failed",
                        {"turn_id": candidate.turn_id, "error_type": type(exc).__name__},
                        turn_id=candidate.turn_id,
                    )
                    ready = False
                if ready:
                    eligible.append(candidate)
            candidates = eligible
        if not policy.fair_principals or len(candidates) <= 1:
            return candidates[:limit]

        grouped: dict[str, list[AgentTurn]] = {}
        for candidate in candidates:
            session = self.session_store.get_session(candidate.session_id)
            principal = session.principal_id or f"session:{session.session_id}"
            grouped.setdefault(principal, []).append(candidate)

        ordered: list[AgentTurn] = []
        now = time.time()
        while grouped and len(ordered) < limit:
            heads: list[tuple[str, AgentTurn, int, tuple[int, float]]] = []
            for principal, queue in grouped.items():
                candidate = queue[0]
                age_steps = max(0, int(max(0.0, now - candidate.created_at) / policy.aging_interval_seconds))
                effective_priority = candidate.priority + age_steps
                deadline_key = (
                    1 if candidate.deadline_at is None else 0,
                    float(candidate.deadline_at or 0.0),
                )
                heads.append((principal, candidate, effective_priority, deadline_key))
            highest = max(item[2] for item in heads)
            eligible = [item for item in heads if item[2] == highest]
            earliest_deadline = min(item[3] for item in eligible)
            eligible = [item for item in eligible if item[3] == earliest_deadline]
            principals = sorted(item[0] for item in eligible)
            selected_principal = principals[self._principal_cursor % len(principals)]
            self._principal_cursor = (self._principal_cursor + 1) % max(1, len(grouped))
            selected = grouped[selected_principal].pop(0)
            if not grouped[selected_principal]:
                del grouped[selected_principal]
            ordered.append(selected)
        return ordered

    def run_once(self, *, limit: int = 1) -> tuple[AgentWorkerResult, ...]:
        """Claim at most ``limit`` queued/resuming turns and execute them."""
        page_limit = max(1, min(int(limit), 100))
        candidates = self._ordered_candidates(page_limit)
        results: list[AgentWorkerResult] = []
        for candidate in candidates:
            expired = self.session_store.expire_queued_turn(candidate.turn_id)
            if expired is not None:
                results.append(AgentWorkerResult(
                    turn_id=expired.turn_id,
                    status=expired.status,
                    claimed=False,
                    error_type="DeadlineExceeded",
                ))
                continue
            session = self.session_store.get_session(candidate.session_id)
            admitted = False
            heartbeat: tuple[threading.Event, threading.Thread] | None = None
            principal = session.principal_id or f"session:{session.session_id}"
            tenant = str((session.state or {}).get("tenant_id") or "")
            admission_key = f"{self.worker_id}:{candidate.turn_id}"
            if self._concurrency_gate is not None:
                admitted = self._concurrency_gate.try_acquire(
                    principal_id=principal,
                    session_id=session.session_id,
                    admission_key=admission_key,
                    worker_id=self.worker_id,
                    tenant_id=tenant,
                )
                if not admitted:
                    continue
            claimed = self.session_store.claim_turn(candidate.turn_id, worker_id=self.worker_id)
            if claimed is None:
                if admitted and self._concurrency_gate is not None:
                    self._concurrency_gate.release(
                        principal_id=principal,
                        session_id=session.session_id,
                        admission_key=admission_key,
                        tenant_id=tenant,
                    )
                continue
            if admitted:
                heartbeat = self._start_admission_heartbeat(admission_key)
            request: AgentWorkerRequest | None = None
            billing_reservation: Any = None
            billing_settled = False
            try:
                request = self.request_resolver(session, claimed)
                request.validate()
                approved_ids = self._approved_ids(session.session_id, claimed.turn_id)
                harness = self.harness_factory(session, claimed, approved_ids)
                if request.billing_reserve is not None:
                    billing_reservation = request.billing_reserve(session, claimed)
                execution = harness.run_turn(
                    session.session_id,
                    claimed.turn_id,
                    model=str(request.model).strip(),
                    llm_caller=request.llm_caller,
                    is_owner=bool(request.is_owner),
                    max_iterations=request.max_iterations,
                    principal_id=session.principal_id or request.principal_id,
                    tenant_id=request.tenant_id,
                    node_id=request.node_id,
                    usage_budget=request.usage_budget,
                )
                if request.billing_settle is not None:
                    request.billing_settle(billing_reservation, execution)
                    billing_settled = True
                results.append(AgentWorkerResult(
                    turn_id=claimed.turn_id,
                    status=execution.turn.status,
                    claimed=True,
                    execution=execution,
                ))
            except Exception as exc:
                if (
                    request is not None
                    and getattr(request, "billing_release", None) is not None
                    and not billing_settled
                ):
                    try:
                        request.billing_release(billing_reservation, exc)
                    except Exception:
                        pass
                results.append(self._fail_claimed_turn(claimed, exc))
            finally:
                if heartbeat is not None:
                    heartbeat[0].set()
                    heartbeat[1].join(timeout=1.0)
                if admitted and self._concurrency_gate is not None:
                    self._concurrency_gate.release(
                        principal_id=principal,
                        session_id=session.session_id,
                        admission_key=admission_key,
                        tenant_id=tenant,
                    )
        return tuple(results)

    def run_until_stopped(
        self,
        stop_event: Any,
        *,
        limit: int = 1,
        poll_interval: float = 0.25,
        max_cycles: int | None = None,
    ) -> tuple[AgentWorkerResult, ...]:
        """Run the durable pickup loop until its owner requests shutdown.

        ``stop_event`` follows ``threading.Event`` (``is_set`` and optional
        ``wait``), while the bounded cycle option keeps embedding and tests
        deterministic. The worker remains provider-neutral and never creates
        work that is absent from the durable session store.
        """
        if not hasattr(stop_event, "is_set") or not callable(stop_event.is_set):
            raise TypeError("stop_event must provide is_set()")
        delay = min(max(float(poll_interval), 0.01), 60.0)
        cycles = 0
        results: list[AgentWorkerResult] = []
        while not bool(stop_event.is_set()):
            if max_cycles is not None and cycles >= max(0, int(max_cycles)):
                break
            cycles += 1
            batch = self.run_once(limit=limit)
            results.extend(batch)
            if batch:
                continue
            waiter = getattr(stop_event, "wait", None)
            if callable(waiter):
                waiter(delay)
            else:
                time.sleep(delay)
        return tuple(results)
