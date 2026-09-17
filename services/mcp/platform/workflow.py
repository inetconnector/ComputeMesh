"""Persistent DAG/workflow execution for the ComputeMesh Agents Platform.

The engine schedules dependency-safe nodes, persists checkpoints, supports
bounded parallel execution and resumes completed work without fabricating
success. Concrete side effects are delegated to the caller (normally the safe
tool executor), so this module never bypasses authorization gates.
"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import asdict, dataclass, field
import hashlib
import json
from pathlib import Path
import sqlite3
import threading
import time
from typing import Any, Callable, Mapping, Sequence


@dataclass(frozen=True)
class WorkflowNode:
    node_id: str
    description: str
    skill_id: str = ""
    dependencies: tuple[str, ...] = ()
    max_attempts: int = 1
    idempotency_key: str | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def validate(self) -> list[str]:
        errors: list[str] = []
        if not self.node_id.strip():
            errors.append("node_id is required")
        if self.node_id in self.dependencies:
            errors.append("node cannot depend on itself")
        if self.max_attempts < 1 or self.max_attempts > 20:
            errors.append("max_attempts must be between 1 and 20")
        return errors


@dataclass(frozen=True)
class WorkflowNodeResult:
    node_id: str
    status: str
    attempts: int
    result: Any = None
    error: str = ""


@dataclass(frozen=True)
class WorkflowResult:
    workflow_id: str
    status: str
    nodes: tuple[WorkflowNodeResult, ...]
    resumed: bool
    definition_digest: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "workflow_id": self.workflow_id,
            "status": self.status,
            "nodes": [asdict(node) for node in self.nodes],
            "resumed": self.resumed,
            "definition_digest": self.definition_digest,
        }


class WorkflowDefinitionError(ValueError):
    pass


class WorkflowStateConflict(RuntimeError):
    pass


class DAGWorkflowEngine:
    """SQLite-backed resumable DAG executor."""

    def __init__(self, db_path: str | Path = ":memory:") -> None:
        self.db_path = str(db_path)
        if self.db_path != ":memory:":
            Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(self.db_path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._db_lock = threading.RLock()
        self._workflow_locks: dict[str, threading.Lock] = {}
        self._locks_lock = threading.Lock()
        with self._conn:
            self._conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS workflows (
                    workflow_id TEXT PRIMARY KEY,
                    definition_digest TEXT NOT NULL,
                    definition_json TEXT NOT NULL,
                    created_at REAL NOT NULL,
                    updated_at REAL NOT NULL
                );
                CREATE TABLE IF NOT EXISTS workflow_nodes (
                    workflow_id TEXT NOT NULL,
                    node_id TEXT NOT NULL,
                    status TEXT NOT NULL,
                    attempts INTEGER NOT NULL,
                    result_json TEXT,
                    error TEXT NOT NULL DEFAULT '',
                    started_at REAL,
                    completed_at REAL,
                    updated_at REAL NOT NULL,
                    PRIMARY KEY(workflow_id, node_id),
                    FOREIGN KEY(workflow_id) REFERENCES workflows(workflow_id) ON DELETE CASCADE
                );
                """
            )

    def close(self) -> None:
        with self._db_lock:
            self._conn.close()

    def _lock_for(self, workflow_id: str) -> threading.Lock:
        with self._locks_lock:
            return self._workflow_locks.setdefault(workflow_id, threading.Lock())

    @staticmethod
    def _definition_payload(nodes: Sequence[WorkflowNode]) -> list[dict[str, Any]]:
        return [
            {
                "node_id": node.node_id,
                "description": node.description,
                "skill_id": node.skill_id,
                "dependencies": list(node.dependencies),
                "max_attempts": node.max_attempts,
                "idempotency_key": node.idempotency_key,
                "metadata": dict(node.metadata),
            }
            for node in sorted(nodes, key=lambda item: item.node_id)
        ]

    @classmethod
    def definition_digest(cls, nodes: Sequence[WorkflowNode]) -> str:
        payload = json.dumps(cls._definition_payload(nodes), sort_keys=True, separators=(",", ":"), default=str)
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()

    @staticmethod
    def validate_dag(nodes: Sequence[WorkflowNode]) -> None:
        if not nodes:
            raise WorkflowDefinitionError("workflow requires at least one node")
        node_map: dict[str, WorkflowNode] = {}
        for node in nodes:
            errors = node.validate()
            if errors:
                raise WorkflowDefinitionError(f"{node.node_id or '<empty>'}: {'; '.join(errors)}")
            if node.node_id in node_map:
                raise WorkflowDefinitionError(f"duplicate node_id: {node.node_id}")
            node_map[node.node_id] = node
        for node in nodes:
            missing = sorted(set(node.dependencies) - set(node_map))
            if missing:
                raise WorkflowDefinitionError(
                    f"node {node.node_id} has missing dependencies: {', '.join(missing)}"
                )
        visiting: set[str] = set()
        visited: set[str] = set()

        def visit(node_id: str, stack: list[str]) -> None:
            if node_id in visited:
                return
            if node_id in visiting:
                start = stack.index(node_id) if node_id in stack else 0
                cycle = stack[start:] + [node_id]
                raise WorkflowDefinitionError(f"dependency cycle: {' -> '.join(cycle)}")
            visiting.add(node_id)
            stack.append(node_id)
            for dependency in node_map[node_id].dependencies:
                visit(dependency, stack)
            stack.pop()
            visiting.remove(node_id)
            visited.add(node_id)

        for node_id in sorted(node_map):
            visit(node_id, [])

    def _ensure_workflow(self, workflow_id: str, nodes: Sequence[WorkflowNode]) -> tuple[str, bool]:
        digest = self.definition_digest(nodes)
        payload = json.dumps(self._definition_payload(nodes), ensure_ascii=False, sort_keys=True, default=str)
        now = time.time()
        with self._db_lock, self._conn:
            existing = self._conn.execute(
                "SELECT definition_digest FROM workflows WHERE workflow_id=?", (workflow_id,)
            ).fetchone()
            if existing:
                if existing["definition_digest"] != digest:
                    raise WorkflowStateConflict(
                        "workflow_id already exists with a different definition"
                    )
                return digest, True
            self._conn.execute(
                "INSERT INTO workflows(workflow_id,definition_digest,definition_json,created_at,updated_at) "
                "VALUES(?,?,?,?,?)",
                (workflow_id, digest, payload, now, now),
            )
            for node in nodes:
                self._conn.execute(
                    "INSERT INTO workflow_nodes(workflow_id,node_id,status,attempts,updated_at) "
                    "VALUES(?,?,?,?,?)",
                    (workflow_id, node.node_id, "PENDING", 0, now),
                )
        return digest, False

    def _state(self, workflow_id: str) -> dict[str, sqlite3.Row]:
        with self._db_lock:
            rows = self._conn.execute(
                "SELECT * FROM workflow_nodes WHERE workflow_id=?", (workflow_id,)
            ).fetchall()
        return {str(row["node_id"]): row for row in rows}

    def _set_running(self, workflow_id: str, node_id: str, attempts: int) -> None:
        now = time.time()
        with self._db_lock, self._conn:
            self._conn.execute(
                "UPDATE workflow_nodes SET status='RUNNING',attempts=?,started_at=COALESCE(started_at,?),"
                "error='',updated_at=? WHERE workflow_id=? AND node_id=?",
                (attempts, now, now, workflow_id, node_id),
            )

    def _set_completed(self, workflow_id: str, node_id: str, attempts: int, result: Any) -> None:
        now = time.time()
        with self._db_lock, self._conn:
            self._conn.execute(
                "UPDATE workflow_nodes SET status='COMPLETED',attempts=?,result_json=?,error='',"
                "completed_at=?,updated_at=? WHERE workflow_id=? AND node_id=?",
                (
                    attempts,
                    json.dumps(result, ensure_ascii=False, sort_keys=True, default=str),
                    now,
                    now,
                    workflow_id,
                    node_id,
                ),
            )
            self._conn.execute(
                "UPDATE workflows SET updated_at=? WHERE workflow_id=?", (now, workflow_id)
            )

    def _set_failed(self, workflow_id: str, node_id: str, attempts: int, error: str) -> None:
        now = time.time()
        with self._db_lock, self._conn:
            self._conn.execute(
                "UPDATE workflow_nodes SET status='FAILED',attempts=?,error=?,completed_at=?,updated_at=? "
                "WHERE workflow_id=? AND node_id=?",
                (attempts, error[:4000], now, now, workflow_id, node_id),
            )

    def _set_blocked(self, workflow_id: str, node_id: str, reason: str) -> None:
        now = time.time()
        with self._db_lock, self._conn:
            self._conn.execute(
                "UPDATE workflow_nodes SET status='BLOCKED',error=?,completed_at=?,updated_at=? "
                "WHERE workflow_id=? AND node_id=? AND status!='COMPLETED'",
                (reason[:4000], now, now, workflow_id, node_id),
            )

    def reset_failed(self, workflow_id: str) -> int:
        """Explicitly reset failed/blocked nodes for a controlled retry."""
        with self._db_lock, self._conn:
            cursor = self._conn.execute(
                "UPDATE workflow_nodes SET status='PENDING',error='',completed_at=NULL,updated_at=? "
                "WHERE workflow_id=? AND status IN ('FAILED','BLOCKED')",
                (time.time(), workflow_id),
            )
            return cursor.rowcount

    def execute(
        self,
        workflow_id: str,
        nodes: Sequence[WorkflowNode],
        runner: Callable[[WorkflowNode], Any],
        *,
        validators: Mapping[str, Callable[[Any], bool]] | None = None,
        max_workers: int = 4,
    ) -> WorkflowResult:
        """Execute ready nodes and persist state after every terminal result.

        A completed node is never re-executed when the same workflow is resumed.
        A failed node is terminal until ``reset_failed`` is explicitly called.
        """
        workflow_id = str(workflow_id or "").strip()
        if not workflow_id:
            raise WorkflowDefinitionError("workflow_id is required")
        self.validate_dag(nodes)
        node_map = {node.node_id: node for node in nodes}
        validators = dict(validators or {})
        workers = max(1, min(32, int(max_workers)))
        lock = self._lock_for(workflow_id)
        if not lock.acquire(blocking=False):
            raise WorkflowStateConflict("workflow is already executing in this process")
        try:
            digest, resumed = self._ensure_workflow(workflow_id, nodes)
            while True:
                state = self._state(workflow_id)
                statuses = {node_id: str(row["status"]) for node_id, row in state.items()}
                for node in nodes:
                    if statuses[node.node_id] in {"COMPLETED", "FAILED", "BLOCKED"}:
                        continue
                    failed_dependencies = [
                        dep for dep in node.dependencies if statuses.get(dep) in {"FAILED", "BLOCKED"}
                    ]
                    if failed_dependencies:
                        self._set_blocked(
                            workflow_id,
                            node.node_id,
                            f"dependency failed: {', '.join(failed_dependencies)}",
                        )
                state = self._state(workflow_id)
                statuses = {node_id: str(row["status"]) for node_id, row in state.items()}
                ready = [
                    node
                    for node in nodes
                    if statuses[node.node_id] in {"PENDING", "RUNNING"}
                    and all(statuses.get(dep) == "COMPLETED" for dep in node.dependencies)
                ]
                # RUNNING from a previous interrupted process is recoverable: its attempt is
                # retried only when it has remaining bounded attempts.
                executable: list[WorkflowNode] = []
                for node in ready:
                    row = state[node.node_id]
                    attempts = int(row["attempts"])
                    if statuses[node.node_id] == "RUNNING" and attempts >= node.max_attempts:
                        self._set_failed(
                            workflow_id,
                            node.node_id,
                            attempts,
                            "interrupted at final allowed attempt",
                        )
                    else:
                        executable.append(node)
                if not executable:
                    break

                def run_node(node: WorkflowNode) -> tuple[str, int, Any, str]:
                    row = self._state(workflow_id)[node.node_id]
                    attempts = int(row["attempts"])
                    last_error = ""
                    while attempts < node.max_attempts:
                        attempts += 1
                        self._set_running(workflow_id, node.node_id, attempts)
                        try:
                            result = runner(node)
                            validator = validators.get(node.node_id)
                            if validator is not None and not validator(result):
                                raise ValueError("node result validation failed")
                            return node.node_id, attempts, result, ""
                        except Exception as exc:  # failure is persisted; success is never inferred
                            last_error = str(exc)
                    return node.node_id, attempts, None, last_error or "node execution failed"

                with ThreadPoolExecutor(max_workers=min(workers, len(executable))) as pool:
                    futures = {pool.submit(run_node, node): node for node in executable}
                    for future in as_completed(futures):
                        node_id, attempts, result, error = future.result()
                        if error:
                            self._set_failed(workflow_id, node_id, attempts, error)
                        else:
                            self._set_completed(workflow_id, node_id, attempts, result)

            final_state = self._state(workflow_id)
            results: list[WorkflowNodeResult] = []
            for node in sorted(nodes, key=lambda item: item.node_id):
                row = final_state[node.node_id]
                result: Any = None
                if row["result_json"] is not None:
                    try:
                        result = json.loads(row["result_json"])
                    except json.JSONDecodeError:
                        result = row["result_json"]
                results.append(
                    WorkflowNodeResult(
                        node_id=node.node_id,
                        status=str(row["status"]),
                        attempts=int(row["attempts"]),
                        result=result,
                        error=str(row["error"] or ""),
                    )
                )
            terminal = {result.status for result in results}
            if terminal == {"COMPLETED"}:
                status = "COMPLETED"
            elif "FAILED" in terminal or "BLOCKED" in terminal:
                status = "PARTIAL_FAILURE"
            else:
                status = "INCOMPLETE"
            return WorkflowResult(workflow_id, status, tuple(results), resumed, digest)
        finally:
            lock.release()
