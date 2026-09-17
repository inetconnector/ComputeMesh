"""Versioned canonical project-state store with atomic checkpoints."""
from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
import tempfile
import time
from typing import Any, Mapping
import uuid


class StaleStateError(RuntimeError):
    pass


@dataclass(frozen=True)
class StateSnapshot:
    version: int
    checksum: str
    updated_at: str
    data: dict[str, Any]


class ProjectStateStore:
    """Machine-readable state store backing human-readable PROJECT_STATE.md.

    Writes use a cross-process lock plus optimistic version checking. Atomic
    ``os.replace`` prevents torn files; the lock prevents two writers that both
    observed version N from silently publishing different version N+1 states.
    """

    def __init__(
        self,
        state_path: str | Path,
        *,
        checkpoint_dir: str | Path | None = None,
        lock_timeout_seconds: float = 10.0,
        stale_lock_seconds: float = 120.0,
    ) -> None:
        self.state_path = Path(state_path)
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        self.checkpoint_dir = Path(
            checkpoint_dir or self.state_path.parent / ".project_state" / "checkpoints"
        )
        self.checkpoint_dir.mkdir(parents=True, exist_ok=True)
        self.lock_path = self.state_path.with_name(self.state_path.name + ".lock")
        self.lock_timeout_seconds = max(0.1, float(lock_timeout_seconds))
        self.stale_lock_seconds = max(5.0, float(stale_lock_seconds))

    @staticmethod
    def new_id(prefix: str) -> str:
        clean = "".join(
            ch for ch in prefix.upper() if ch.isalnum() or ch == "-"
        ).strip("-") or "ID"
        return f"{clean}-{uuid.uuid4().hex[:12].upper()}"

    @staticmethod
    def _canonical_bytes(data: Mapping[str, Any]) -> bytes:
        return json.dumps(
            data,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            default=str,
        ).encode("utf-8")

    @classmethod
    def checksum(cls, data: Mapping[str, Any]) -> str:
        return hashlib.sha256(cls._canonical_bytes(data)).hexdigest()

    @staticmethod
    def _iso_now() -> str:
        return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())

    @contextmanager
    def _write_lock(self):
        deadline = time.monotonic() + self.lock_timeout_seconds
        fd: int | None = None
        while fd is None:
            try:
                fd = os.open(
                    str(self.lock_path),
                    os.O_CREAT | os.O_EXCL | os.O_WRONLY,
                    0o600,
                )
                os.write(fd, f"pid={os.getpid()} time={time.time()}\n".encode("ascii"))
                os.fsync(fd)
            except FileExistsError:
                try:
                    age = time.time() - self.lock_path.stat().st_mtime
                    if age > self.stale_lock_seconds:
                        self.lock_path.unlink(missing_ok=True)
                        continue
                except FileNotFoundError:
                    continue
                if time.monotonic() >= deadline:
                    raise TimeoutError(f"project state write lock timed out: {self.lock_path}")
                time.sleep(0.05)
        try:
            yield
        finally:
            try:
                if fd is not None:
                    os.close(fd)
            finally:
                self.lock_path.unlink(missing_ok=True)

    def _atomic_write(self, path: Path, payload: bytes) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp_name = tempfile.mkstemp(
            prefix=f".{path.name}.",
            suffix=".tmp",
            dir=str(path.parent),
        )
        try:
            with os.fdopen(fd, "wb") as handle:
                handle.write(payload)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(tmp_name, path)
            try:
                directory_fd = os.open(str(path.parent), os.O_RDONLY)
            except OSError:
                directory_fd = None
            if directory_fd is not None:
                try:
                    os.fsync(directory_fd)
                finally:
                    os.close(directory_fd)
        finally:
            if os.path.exists(tmp_name):
                os.unlink(tmp_name)

    def initialize(
        self,
        project_id: str,
        project_name: str,
        primary_goal: str,
        *,
        extra: Mapping[str, Any] | None = None,
    ) -> StateSnapshot:
        if self.state_path.exists():
            raise FileExistsError(self.state_path)
        now = self._iso_now()
        data: dict[str, Any] = {
            "document_type": "PROJECT_STATE",
            "state_schema_version": "1.0",
            "project_state_version": 1,
            "project_id": project_id,
            "project_name": project_name,
            "status": "ACTIVE",
            "created_at": now,
            "updated_at": now,
            "primary_goal": primary_goal,
            "known_facts": [],
            "requirements": [],
            "assumptions": [],
            "decisions": [],
            "open_questions": [],
            "tasks": [],
            "dependencies": [],
            "milestones": [],
            "artifacts": [],
            "evidence": [],
            "calculations": [],
            "risks": [],
            "issues": [],
            "tests": [],
            "security_privacy": [],
            "actions": [],
            "checkpoints": [],
            "next_steps": [],
            "superseded": [],
            "change_log": [],
        }
        if extra:
            for key, value in extra.items():
                if key not in {"project_state_version", "created_at", "updated_at"}:
                    data[key] = value
        return self.save(data, expected_version=0, change="initialize")

    def _load_unlocked(self) -> StateSnapshot:
        if not self.state_path.exists():
            raise FileNotFoundError(self.state_path)
        data = json.loads(self.state_path.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            raise ValueError("project state root must be an object")
        version = int(data.get("project_state_version", 0))
        if version < 1:
            raise ValueError("invalid project_state_version")
        return StateSnapshot(
            version,
            self.checksum(data),
            str(data.get("updated_at", "")),
            data,
        )

    def load(self) -> StateSnapshot:
        return self._load_unlocked()

    def save(
        self,
        state: Mapping[str, Any],
        *,
        expected_version: int,
        change: str = "update",
    ) -> StateSnapshot:
        with self._write_lock():
            current_version = 0
            current: dict[str, Any] | None = None
            if self.state_path.exists():
                current_snapshot = self._load_unlocked()
                current_version = current_snapshot.version
                current = current_snapshot.data
            if current_version != expected_version:
                raise StaleStateError(
                    f"expected project state version {expected_version}, found {current_version}"
                )
            new_state = dict(state)
            new_version = current_version + 1
            new_state["document_type"] = "PROJECT_STATE"
            new_state.setdefault("state_schema_version", "1.0")
            new_state["project_state_version"] = new_version
            new_state.setdefault(
                "created_at",
                (current or {}).get("created_at", self._iso_now()),
            )
            new_state["updated_at"] = self._iso_now()
            change_log = list(new_state.get("change_log") or [])
            change_log.append({
                "change_id": self.new_id("CHG"),
                "version": new_version,
                "timestamp": new_state["updated_at"],
                "change": change,
            })
            new_state["change_log"] = change_log
            payload = (
                json.dumps(
                    new_state,
                    ensure_ascii=False,
                    sort_keys=True,
                    indent=2,
                    default=str,
                ).encode("utf-8")
                + b"\n"
            )
            self._atomic_write(self.state_path, payload)
            return StateSnapshot(
                new_version,
                self.checksum(new_state),
                new_state["updated_at"],
                new_state,
            )

    def update(
        self,
        mutator: Any,
        *,
        expected_version: int,
        change: str = "update",
    ) -> StateSnapshot:
        snapshot = self.load()
        if snapshot.version != expected_version:
            raise StaleStateError(
                f"expected project state version {expected_version}, found {snapshot.version}"
            )
        draft = json.loads(json.dumps(snapshot.data, ensure_ascii=False, default=str))
        result = mutator(draft)
        return self.save(
            result if isinstance(result, dict) else draft,
            expected_version=expected_version,
            change=change,
        )

    def checkpoint(
        self,
        *,
        expected_version: int,
        reason: str = "checkpoint",
    ) -> dict[str, Any]:
        snapshot = self.load()
        if snapshot.version != expected_version:
            raise StaleStateError(
                f"expected project state version {expected_version}, found {snapshot.version}"
            )
        checkpoint_id = f"CP-{snapshot.version:06d}-{snapshot.checksum[:12]}"
        checkpoint_path = self.checkpoint_dir / f"{checkpoint_id}.json"
        self._atomic_write(
            checkpoint_path,
            json.dumps(
                snapshot.data,
                ensure_ascii=False,
                sort_keys=True,
                indent=2,
                default=str,
            ).encode("utf-8") + b"\n",
        )
        return {
            "checkpoint_id": checkpoint_id,
            "project_state_version": snapshot.version,
            "checksum": snapshot.checksum,
            "reason": reason,
            "path": str(checkpoint_path),
        }

    def restore_checkpoint(
        self,
        checkpoint_id: str,
        *,
        expected_version: int,
    ) -> StateSnapshot:
        snapshot = self.load()
        if snapshot.version != expected_version:
            raise StaleStateError(
                f"expected project state version {expected_version}, found {snapshot.version}"
            )
        path = self.checkpoint_dir / f"{checkpoint_id}.json"
        data = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            raise ValueError("checkpoint is invalid")
        data["previous_checkpoint"] = checkpoint_id
        return self.save(
            data,
            expected_version=expected_version,
            change=f"restore checkpoint {checkpoint_id}",
        )

    def import_legacy_state_reference(
        self,
        legacy_path: str | Path,
        *,
        expected_version: int,
    ) -> StateSnapshot:
        legacy = Path(legacy_path).resolve()
        if not legacy.exists():
            raise FileNotFoundError(legacy)
        digest = hashlib.sha256(legacy.read_bytes()).hexdigest()

        def mutate(state: dict[str, Any]) -> None:
            artifacts = list(state.get("artifacts") or [])
            artifacts.append({
                "artifact_id": self.new_id("ART"),
                "type": "LEGACY_STATE_REFERENCE",
                "path": str(legacy),
                "checksum": digest,
                "migration_status": "REFERENCED_NOT_REPLACED",
            })
            state["artifacts"] = artifacts

        return self.update(
            mutate,
            expected_version=expected_version,
            change="reference legacy state.md",
        )