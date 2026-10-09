"""Immutable, content-addressed Agent artifacts with scoped access."""
from __future__ import annotations

import hashlib
import os
import re
import sqlite3
import tempfile
import threading
import time
import uuid
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Iterator, Mapping


class ArtifactError(RuntimeError):
    """Base artifact storage error."""


class ArtifactAccessDenied(ArtifactError):
    """Raised when a caller is not authorized to read an artifact reference."""


class ArtifactNotFound(ArtifactError):
    """Raised when artifact metadata or bytes are missing."""


@dataclass(frozen=True)
class ArtifactRef:
    ref_id: str
    artifact_id: str
    session_id: str
    turn_id: str
    principal_id: str
    name: str
    producer: str
    mime_type: str
    size_bytes: int
    created_at: float
    expires_at: float | None
    signature_status: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "ref_id": self.ref_id,
            "artifact_id": self.artifact_id,
            "session_id": self.session_id,
            "turn_id": self.turn_id,
            "principal_id": self.principal_id,
            "name": self.name,
            "producer": self.producer,
            "mime_type": self.mime_type,
            "size_bytes": self.size_bytes,
            "created_at": self.created_at,
            "expires_at": self.expires_at,
            "signature_status": self.signature_status,
        }


@dataclass(frozen=True)
class ArtifactChunk:
    """One bounded, integrity-checked slice of an immutable artifact."""

    ref: ArtifactRef
    offset: int
    data: bytes
    total_bytes: int

    @property
    def end_offset(self) -> int:
        return self.offset + len(self.data)

    @property
    def complete(self) -> bool:
        return self.end_offset >= self.total_bytes


_MIME = re.compile(r"^[A-Za-z0-9.+-]+/[A-Za-z0-9.+-]+$")


class ArtifactStore:
    """Store bytes by SHA-256 while keeping scoped immutable references."""

    def __init__(
        self,
        root: str | Path,
        database: str | Path = ":memory:",
        *,
        max_bytes: int = 128 * 1024 * 1024,
        event_sink: Callable[[str, Mapping[str, Any]], None] | None = None,
    ) -> None:
        self.root = Path(root).resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        self.database = Path(database)
        if str(database) != ":memory:":
            self.database.parent.mkdir(parents=True, exist_ok=True)
        self.max_bytes = max(1, int(max_bytes))
        self.event_sink = event_sink
        self._lock = threading.RLock()
        self._verified_files: dict[str, tuple[int, int, int]] = {}
        self._connection = sqlite3.connect(str(database), check_same_thread=False, timeout=30.0)
        self._connection.row_factory = sqlite3.Row
        self._connection.execute("PRAGMA foreign_keys = ON")
        self._connection.execute("PRAGMA busy_timeout = 30000")
        if str(database) != ":memory:":
            self._connection.execute("PRAGMA journal_mode = WAL")
        self._create_schema()

    def _create_schema(self) -> None:
        with self._transaction() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS artifacts (
                    artifact_id TEXT PRIMARY KEY,
                    storage_path TEXT NOT NULL,
                    mime_type TEXT NOT NULL,
                    size_bytes INTEGER NOT NULL,
                    created_at REAL NOT NULL,
                    expires_at REAL,
                    signature_status TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS artifact_refs (
                    ref_id TEXT PRIMARY KEY,
                    artifact_id TEXT NOT NULL REFERENCES artifacts(artifact_id) ON DELETE CASCADE,
                    session_id TEXT NOT NULL,
                    turn_id TEXT NOT NULL,
                    principal_id TEXT NOT NULL,
                    name TEXT NOT NULL,
                    producer TEXT NOT NULL,
                    created_at REAL NOT NULL,
                    expires_at REAL
                );
                CREATE INDEX IF NOT EXISTS artifact_refs_session_idx ON artifact_refs(session_id, created_at);
                """
            )
            columns = {
                str(row["name"])
                for row in self._connection.execute("PRAGMA table_info(artifact_refs)").fetchall()
            }
            if "expires_at" not in columns:
                self._connection.execute("ALTER TABLE artifact_refs ADD COLUMN expires_at REAL")
                self._connection.execute(
                    "UPDATE artifact_refs SET expires_at = (SELECT expires_at FROM artifacts WHERE artifacts.artifact_id = artifact_refs.artifact_id) WHERE expires_at IS NULL"
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

    def _emit(self, event_type: str, payload: Mapping[str, Any]) -> None:
        if self.event_sink is not None:
            self.event_sink(event_type, dict(payload))

    def _storage_path(self, artifact_id: str) -> Path:
        digest = artifact_id.removeprefix("sha256:")
        path = self.root / "sha256" / digest[:2] / digest
        if self.root not in path.resolve().parents:
            raise ArtifactError("artifact path escaped storage root")
        return path

    @staticmethod
    def _validate_name(name: str) -> None:
        if not 1 <= len(str(name)) <= 256 or "/" in str(name) or "\\" in str(name) or str(name) in {".", ".."}:
            raise ValueError("artifact name must be a single bounded filename")

    def put_bytes(
        self,
        data: bytes,
        *,
        session_id: str,
        turn_id: str,
        principal_id: str,
        name: str,
        mime_type: str,
        producer: str = "agent",
        expires_at: float | None = None,
        signature_status: str = "unsigned",
        ref_id: str | None = None,
    ) -> ArtifactRef:
        raw = bytes(data)
        if len(raw) > self.max_bytes:
            raise ArtifactError("artifact exceeds configured size limit")
        self._validate_name(name)
        if not _MIME.fullmatch(str(mime_type)):
            raise ValueError("mime_type must be a valid type/subtype")
        if not principal_id or not session_id or not turn_id:
            raise ValueError("session_id, turn_id and principal_id are required")
        if expires_at is not None and float(expires_at) <= time.time():
            raise ValueError("expires_at must be in the future")
        digest = hashlib.sha256(raw).hexdigest()
        artifact_id = f"sha256:{digest}"
        path = self._storage_path(artifact_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        if not path.exists():
            temporary = tempfile.NamedTemporaryFile(prefix=".artifact-", dir=path.parent, delete=False)
            temporary_path = Path(temporary.name)
            try:
                with temporary:
                    temporary.write(raw)
                    temporary.flush()
                    os.fsync(temporary.fileno())
                os.replace(temporary_path, path)
            finally:
                temporary_path.unlink(missing_ok=True)
        now = time.time()
        ref_id = str(ref_id or f"aref_{uuid.uuid4().hex}")
        with self._transaction() as connection:
            connection.execute(
                "INSERT OR IGNORE INTO artifacts (artifact_id, storage_path, mime_type, size_bytes, created_at, expires_at, signature_status) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (artifact_id, str(path), str(mime_type), len(raw), now, expires_at, str(signature_status)),
            )
            try:
                connection.execute(
                    "INSERT INTO artifact_refs (ref_id, artifact_id, session_id, turn_id, principal_id, name, producer, created_at, expires_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (ref_id, artifact_id, str(session_id), str(turn_id), str(principal_id), str(name), str(producer), now, expires_at),
                )
            except sqlite3.IntegrityError as exc:
                raise ArtifactError(f"artifact reference already exists: {ref_id}") from exc
            ref = self._ref(connection.execute("SELECT r.*, r.expires_at AS ref_expires_at, a.mime_type, a.size_bytes, a.signature_status FROM artifact_refs r JOIN artifacts a ON a.artifact_id = r.artifact_id WHERE r.ref_id = ?", (ref_id,)).fetchone())
            self._emit("artifact.created", {"ref_id": ref.ref_id, "artifact_id": ref.artifact_id, "session_id": ref.session_id, "turn_id": ref.turn_id, "mime_type": ref.mime_type, "size_bytes": ref.size_bytes})
            return ref

    @staticmethod
    def _ref(row: sqlite3.Row) -> ArtifactRef:
        return ArtifactRef(
            ref_id=str(row["ref_id"]),
            artifact_id=str(row["artifact_id"]),
            session_id=str(row["session_id"]),
            turn_id=str(row["turn_id"]),
            principal_id=str(row["principal_id"]),
            name=str(row["name"]),
            producer=str(row["producer"]),
            mime_type=str(row["mime_type"]),
            size_bytes=int(row["size_bytes"]),
            created_at=float(row["created_at"]),
            expires_at=float(row["ref_expires_at"]) if row["ref_expires_at"] is not None else None,
            signature_status=str(row["signature_status"]),
        )

    def get_ref(self, ref_id: str, *, principal_id: str) -> ArtifactRef:
        with self._lock:
            row = self._connection.execute("SELECT r.*, r.expires_at AS ref_expires_at, a.mime_type, a.size_bytes, a.signature_status FROM artifact_refs r JOIN artifacts a ON a.artifact_id = r.artifact_id WHERE r.ref_id = ?", (str(ref_id),)).fetchone()
        if row is None:
            raise ArtifactNotFound("artifact reference not found")
        ref = self._ref(row)
        if ref.principal_id != str(principal_id):
            raise ArtifactAccessDenied("artifact reference belongs to a different principal")
        if ref.expires_at is not None and ref.expires_at <= time.time():
            raise ArtifactNotFound("artifact has expired")
        return ref

    def read_bytes(self, ref_id: str, *, principal_id: str) -> bytes:
        ref = self.get_ref(ref_id, principal_id=principal_id)
        path = self._verify_storage_file(ref)
        data = path.read_bytes()
        if hashlib.sha256(data).hexdigest() != ref.artifact_id.removeprefix("sha256:"):
            raise ArtifactError("artifact digest verification failed")
        return data

    def read_chunk(
        self,
        ref_id: str,
        *,
        principal_id: str,
        offset: int = 0,
        length: int = 1024 * 1024,
    ) -> ArtifactChunk:
        """Read one bounded verified slice for resumable artifact transfer."""
        if isinstance(offset, bool) or isinstance(length, bool):
            raise ValueError("artifact chunk offset and length must be integers")
        offset = int(offset)
        length = int(length)
        if offset < 0 or length < 1 or length > 4 * 1024 * 1024:
            raise ValueError("artifact chunk bounds are invalid")
        ref = self.get_ref(ref_id, principal_id=principal_id)
        if offset >= ref.size_bytes:
            raise ArtifactNotFound("artifact chunk offset is outside the artifact")
        path = self._verify_storage_file(ref)
        with path.open("rb") as handle:
            handle.seek(offset)
            data = handle.read(length)
        return ArtifactChunk(
            ref=ref,
            offset=offset,
            data=data,
            total_bytes=ref.size_bytes,
        )

    def _verify_storage_file(self, ref: ArtifactRef) -> Path:
        """Verify an immutable blob once, then allow bounded random reads."""
        path = self._storage_path(ref.artifact_id)
        try:
            metadata = path.stat()
        except FileNotFoundError as exc:
            raise ArtifactNotFound("artifact bytes are missing") from exc
        if not path.is_file() or metadata.st_size != ref.size_bytes:
            raise ArtifactError("artifact storage metadata does not match the reference")
        marker = (int(metadata.st_ino), int(metadata.st_size), int(metadata.st_mtime_ns))
        with self._lock:
            if self._verified_files.get(ref.artifact_id) == marker:
                return path
        digest = hashlib.sha256()
        with path.open("rb") as handle:
            for block in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(block)
        if digest.hexdigest() != ref.artifact_id.removeprefix("sha256:"):
            raise ArtifactError("artifact digest verification failed")
        with self._lock:
            self._verified_files[ref.artifact_id] = marker
        return path

    def list_for_session(self, session_id: str, *, principal_id: str) -> tuple[ArtifactRef, ...]:
        with self._lock:
            rows = self._connection.execute("SELECT r.*, r.expires_at AS ref_expires_at, a.mime_type, a.size_bytes, a.signature_status FROM artifact_refs r JOIN artifacts a ON a.artifact_id = r.artifact_id WHERE r.session_id = ? AND r.principal_id = ? AND (r.expires_at IS NULL OR r.expires_at > ?) ORDER BY r.created_at", (str(session_id), str(principal_id), time.time())).fetchall()
        return tuple(self._ref(row) for row in rows)

    def purge_expired(self, *, now: float | None = None) -> int:
        timestamp = time.time() if now is None else float(now)
        removed = 0
        with self._transaction() as connection:
            connection.execute("DELETE FROM artifact_refs WHERE expires_at IS NOT NULL AND expires_at <= ?", (timestamp,))
            rows = connection.execute(
                "SELECT a.artifact_id, a.storage_path FROM artifacts a LEFT JOIN artifact_refs r ON r.artifact_id = a.artifact_id WHERE r.ref_id IS NULL AND (a.expires_at IS NULL OR a.expires_at <= ?)",
                (timestamp,),
            ).fetchall()
            for row in rows:
                connection.execute("DELETE FROM artifacts WHERE artifact_id = ?", (str(row["artifact_id"]),))
                Path(str(row["storage_path"])).unlink(missing_ok=True)
                removed += 1
        return removed

    def close(self) -> None:
        with self._lock:
            self._connection.close()

    def __enter__(self) -> "ArtifactStore":
        return self

    def __exit__(self, *exc: Any) -> None:
        self.close()
