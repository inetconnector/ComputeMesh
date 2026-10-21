import time
from typing import Any, Dict, List, Optional, Set, Tuple, Protocol
from datetime import datetime, timezone
import sqlite3
import json
import hashlib

class HardeningPart7Error(RuntimeError):
    pass

class StatefulIdempotencyError(HardeningPart7Error):
    pass

class StatefulCapacityLeaseError(HardeningPart7Error):
    pass

class SQLiteConnectionProvider(Protocol):
    def get_connection(self) -> sqlite3.Connection:
        ...

class StatefulIdempotentCommandEnforcer:
    """Enforces: 'Every state-changing command MUST be idempotent or carry an idempotency key.'"""
    def __init__(self, db: sqlite3.Connection):
        self._db = db
        self._migrate()

    def _execute_with_savepoint(self, savepoint_name: str, fn: Any) -> Any:
        self._db.execute(f"SAVEPOINT {savepoint_name}")
        try:
            result = fn()
            self._db.execute(f"RELEASE SAVEPOINT {savepoint_name}")
            # Ensure compatibility with isolation_level="" by committing
            if self._db.isolation_level is not None:
                self._db.commit()
            return result
        except Exception:
            self._db.execute(f"ROLLBACK TO SAVEPOINT {savepoint_name}")
            raise

    def _migrate(self):
        def _do_migrate():
            self._db.execute('''
                CREATE TABLE IF NOT EXISTS part7_idempotency_log (
                    idempotency_key TEXT PRIMARY KEY,
                    command_type TEXT NOT NULL,
                    result_json TEXT NOT NULL,
                    executed_at TEXT NOT NULL
                )
            ''')
        self._execute_with_savepoint("part7_migrate", _do_migrate)

    def execute_command(self, command: Dict[str, Any], execute_fn: Any) -> Dict[str, Any]:
        is_state_changing = command.get("is_state_changing", False)
        is_idempotent_by_design = command.get("is_idempotent_by_design", False)
        idempotency_key = command.get("idempotency_key")

        if is_state_changing and not is_idempotent_by_design and not idempotency_key:
            raise StatefulIdempotencyError("Every state-changing command MUST be idempotent or carry an idempotency key.")

        if not is_state_changing or is_idempotent_by_design:
            return execute_fn()

        if idempotency_key:
            # Check if it was already executed
            def _check():
                row = self._db.execute("SELECT result_json FROM part7_idempotency_log WHERE idempotency_key=?", (idempotency_key,)).fetchone()
                if row:
                    return json.loads(row[0])
                return None

            existing = self._execute_with_savepoint(f"idempotency_check_{hashlib.md5(idempotency_key.encode()).hexdigest()}", _check)
            if existing:
                existing["_idempotent_replay"] = True
                return existing

            # Execute the actual logic outside of the savepoint transaction
            # because execute_fn might manage its own nested DB transactions (e.g. SQLiteStateStore transitions)
            result = execute_fn()

            # Log successful execution
            def _record():
                self._db.execute("INSERT INTO part7_idempotency_log(idempotency_key, command_type, result_json, executed_at) VALUES(?, ?, ?, ?)",
                                 (idempotency_key, command.get("type", "unknown"), json.dumps(result), datetime.now(timezone.utc).isoformat()))
            self._execute_with_savepoint(f"idempotency_record_{hashlib.md5(idempotency_key.encode()).hexdigest()}", _record)
            return result

        return execute_fn()

class StatefulCapacityLeaseManager:
    """Enforces: 'Capacity MUST be leased/reserved before job dispatch to avoid placement races.'
    and 'Expired leases MUST release capacity automatically.'"""
    def __init__(self, db: sqlite3.Connection, total_capacity: int):
        self._db = db
        self.total_capacity = total_capacity
        self._migrate()

    def _execute_with_savepoint(self, savepoint_name: str, fn: Any) -> Any:
        self._db.execute(f"SAVEPOINT {savepoint_name}")
        try:
            result = fn()
            self._db.execute(f"RELEASE SAVEPOINT {savepoint_name}")
            if self._db.isolation_level is not None:
                self._db.commit()
            return result
        except Exception:
            self._db.execute(f"ROLLBACK TO SAVEPOINT {savepoint_name}")
            raise

    def _migrate(self):
        def _do_migrate():
            self._db.execute('''
                CREATE TABLE IF NOT EXISTS part7_capacity_leases (
                    lease_id TEXT PRIMARY KEY,
                    amount INTEGER NOT NULL,
                    expires_at REAL NOT NULL,
                    job_id TEXT
                )
            ''')
        self._execute_with_savepoint("part7_capacity_migrate", _do_migrate)

    def lease_capacity(self, lease_id: str, amount: int, ttl_seconds: int = 60) -> bool:
        def _do_lease():
            self._expire_leases()
            row = self._db.execute("SELECT SUM(amount) FROM part7_capacity_leases").fetchone()
            used_capacity = row[0] if row[0] is not None else 0

            if self.total_capacity - used_capacity < amount:
                return False

            row = self._db.execute("SELECT lease_id FROM part7_capacity_leases WHERE lease_id=?", (lease_id,)).fetchone()
            if row:
                raise StatefulCapacityLeaseError(f"Lease {lease_id} already exists.")

            self._db.execute("INSERT INTO part7_capacity_leases(lease_id, amount, expires_at) VALUES(?, ?, ?)",
                             (lease_id, amount, time.time() + ttl_seconds))
            return True
        return self._execute_with_savepoint(f"lease_{hashlib.md5(lease_id.encode()).hexdigest()}", _do_lease)

    def dispatch_job(self, job_id: str, required_capacity: int, lease_id: Optional[str] = None) -> bool:
        def _do_dispatch():
            self._expire_leases()

            if not lease_id:
                raise StatefulCapacityLeaseError("Capacity MUST be leased/reserved before job dispatch to avoid placement races.")

            row = self._db.execute("SELECT amount, job_id FROM part7_capacity_leases WHERE lease_id=?", (lease_id,)).fetchone()
            if not row:
                 raise StatefulCapacityLeaseError("Capacity MUST be leased/reserved before job dispatch to avoid placement races.")

            amount, existing_job_id = row
            if amount < required_capacity:
                 raise StatefulCapacityLeaseError(f"Lease {lease_id} has insufficient capacity ({amount}) for job {job_id} ({required_capacity}).")

            if existing_job_id and existing_job_id != job_id:
                 raise StatefulCapacityLeaseError(f"Lease {lease_id} is already bound to job {existing_job_id}.")

            self._db.execute("UPDATE part7_capacity_leases SET job_id=? WHERE lease_id=?", (job_id, lease_id))
            return True
        return self._execute_with_savepoint(f"dispatch_{hashlib.md5(job_id.encode()).hexdigest()}", _do_dispatch)

    def release_lease(self, lease_id: str) -> None:
        def _do_release():
            self._db.execute("DELETE FROM part7_capacity_leases WHERE lease_id=?", (lease_id,))
        self._execute_with_savepoint(f"release_{hashlib.md5(lease_id.encode()).hexdigest()}", _do_release)

    def _expire_leases(self) -> None:
        """Enforces: 'Expired leases MUST release capacity automatically.'"""
        current_time = time.time()
        self._db.execute("DELETE FROM part7_capacity_leases WHERE expires_at <= ?", (current_time,))

    def get_available_capacity(self) -> int:
        def _do_get():
            self._expire_leases()
            row = self._db.execute("SELECT SUM(amount) FROM part7_capacity_leases").fetchone()
            used_capacity = row[0] if row[0] is not None else 0
            return self.total_capacity - used_capacity
        return self._execute_with_savepoint("get_capacity", _do_get)
