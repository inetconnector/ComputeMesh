# SPDX-License-Identifier: Apache-2.0
"""Bounded local workspace transport for self-hosted agent environments.

This is a filesystem workspace adapter, not a process sandbox. It deliberately
implements no shell, subprocess or arbitrary command operation. Production
mesh execution continues to use the authenticated NodeOS environment
transport.
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import json
import secrets
import threading
import time
from pathlib import Path, PurePosixPath
from typing import Any, Mapping

from .artifacts import ArtifactStore
from .environment import (
    EnvironmentError,
    EnvironmentLease,
    EnvironmentOperation,
    EnvironmentPolicyDenied,
    EnvironmentRequest,
    EnvironmentSpec,
)


class LocalWorkspaceError(EnvironmentError):
    """Raised when a bounded local workspace operation cannot be completed."""


class LocalWorkspaceTransport:
    """Provide bounded file/artifact operations for ``self_hosted`` envs."""

    def __init__(
        self,
        root: str | Path,
        *,
        artifact_store: ArtifactStore | None = None,
        principal_id: str = "local",
        max_file_bytes: int = 8 * 1024 * 1024,
        allow_mesh: bool = False,
        clock: Any = time.time,
    ) -> None:
        self.root = Path(root).resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        self.artifact_store = artifact_store
        self.principal_id = str(principal_id)
        self.max_file_bytes = max(1, min(128 * 1024 * 1024, int(max_file_bytes)))
        self.allow_mesh = bool(allow_mesh)
        self.clock = clock
        self._lock = threading.RLock()
        self._leases: dict[str, tuple[str, Path, int]] = {}
        self._idempotency: dict[tuple[str, str], tuple[str, dict[str, Any]]] = {}

    def _workspace_path(self, spec: EnvironmentSpec) -> Path:
        candidate = self.root / "sessions" / spec.session_id / spec.environment_id
        resolved = candidate.resolve()
        if resolved != self.root and self.root not in resolved.parents:
            raise LocalWorkspaceError("workspace escaped transport root")
        resolved.mkdir(parents=True, exist_ok=True)
        return resolved

    @staticmethod
    def _relative_path(raw: Any) -> PurePosixPath:
        value = str(raw or "")
        if not value or "\\" in value:
            raise LocalWorkspaceError("workspace path must be a non-empty POSIX-relative path")
        parsed = PurePosixPath(value)
        if parsed.is_absolute() or ".." in parsed.parts or "." in parsed.parts:
            raise LocalWorkspaceError("workspace path escapes the environment")
        return parsed

    def _safe_path(self, workspace: Path, raw: Any) -> Path:
        relative = self._relative_path(raw)
        candidate = (workspace / Path(*relative.parts)).resolve()
        if candidate != workspace and workspace not in candidate.parents:
            raise LocalWorkspaceError("workspace path escapes the environment")
        # A symlink anywhere in an existing path could redirect a write/read.
        current = workspace
        for part in relative.parts:
            current = current / part
            if current.is_symlink():
                raise LocalWorkspaceError("symlink paths are not allowed")
        return candidate

    def _lease_workspace(self, lease: EnvironmentLease) -> Path:
        with self._lock:
            record = self._leases.get(lease.lease_id)
        if record is None or record[0] != lease.environment_id:
            raise LocalWorkspaceError("unknown workspace lease")
        if lease.expires_at <= float(self.clock()):
            raise LocalWorkspaceError("workspace lease has expired")
        return record[1]

    def prepare(self, spec: EnvironmentSpec) -> EnvironmentLease:
        allowed_kinds = {"self_hosted"}
        if self.allow_mesh:
            allowed_kinds.add("mesh")
        if str(spec.kind.value) not in allowed_kinds:
            raise LocalWorkspaceError("local workspace transport does not allow this environment kind")
        workspace = self._workspace_path(spec)
        now = float(self.clock())
        lease = EnvironmentLease(
            lease_id=f"localws_{secrets.token_hex(16)}",
            environment_id=spec.environment_id,
            issued_at=now,
            expires_at=now + int(spec.lease_seconds),
            revision=1,
        )
        with self._lock:
            self._leases[lease.lease_id] = (spec.environment_id, workspace, lease.revision)
        return lease

    def heartbeat(self, lease: EnvironmentLease) -> EnvironmentLease:
        workspace = self._lease_workspace(lease)
        now = float(self.clock())
        renewed = EnvironmentLease(
            lease_id=lease.lease_id,
            environment_id=lease.environment_id,
            issued_at=lease.issued_at,
            expires_at=max(lease.expires_at, now + 1),
            revision=lease.revision + 1,
        )
        with self._lock:
            self._leases[lease.lease_id] = (lease.environment_id, workspace, renewed.revision)
        return renewed

    def _idempotency_digest(self, request: EnvironmentRequest) -> str:
        encoded = json.dumps(dict(request.payload), ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)
        return hashlib.sha256(f"{request.operation.value}\0{encoded}".encode("utf-8")).hexdigest()

    def _replay_idempotent(self, lease: EnvironmentLease, request: EnvironmentRequest) -> dict[str, Any] | None:
        if not request.idempotency_key:
            return None
        key = (lease.environment_id, request.idempotency_key)
        with self._lock:
            prior = self._idempotency.get(key)
            if prior is not None:
                if prior[0] != self._idempotency_digest(request):
                    raise LocalWorkspaceError("idempotency key reused with different workspace request")
                return dict(prior[1], idempotency_replay=True)
        return None

    def _remember_idempotent(self, lease: EnvironmentLease, request: EnvironmentRequest, result: dict[str, Any]) -> dict[str, Any]:
        if not request.idempotency_key:
            return result
        key = (lease.environment_id, request.idempotency_key)
        digest = self._idempotency_digest(request)
        with self._lock:
            prior = self._idempotency.get(key)
            if prior is not None:
                if prior[0] != digest:
                    raise LocalWorkspaceError("idempotency key reused with different workspace request")
                return dict(prior[1], idempotency_replay=True)
            stored = dict(result, idempotency_replay=False)
            self._idempotency[key] = (digest, stored)
            return dict(stored)

    def execute(self, lease: EnvironmentLease, request: EnvironmentRequest) -> Mapping[str, Any]:
        workspace = self._lease_workspace(lease)
        if request.operation is EnvironmentOperation.HEALTH:
            return {"status": "healthy", "environment_id": lease.environment_id}
        if request.operation is EnvironmentOperation.WORKSPACE_READ:
            target = self._safe_path(workspace, request.payload.get("path"))
            if not target.is_file():
                raise LocalWorkspaceError("workspace file not found")
            size = target.stat().st_size
            if size > self.max_file_bytes:
                raise LocalWorkspaceError("workspace file exceeds the read limit")
            data = target.read_bytes()
            return {"path": str(request.payload["path"]), "content": data.decode("utf-8", errors="replace"), "size_bytes": len(data)}
        if request.operation is EnvironmentOperation.WORKSPACE_WRITE:
            replay = self._replay_idempotent(lease, request)
            if replay is not None:
                return replay
            target = self._safe_path(workspace, request.payload.get("path"))
            raw_content = request.payload.get("content")
            if not isinstance(raw_content, str):
                raise LocalWorkspaceError("workspace content must be text")
            data = raw_content.encode("utf-8")
            if len(data) > self.max_file_bytes:
                raise LocalWorkspaceError("workspace file exceeds the write limit")
            if target.exists() and not bool(request.payload.get("overwrite", False)):
                raise LocalWorkspaceError("workspace file already exists")
            target.parent.mkdir(parents=True, exist_ok=True)
            temporary = target.with_name(f".{target.name}.{secrets.token_hex(8)}.tmp")
            try:
                temporary.write_bytes(data)
                temporary.replace(target)
            finally:
                temporary.unlink(missing_ok=True)
            return self._remember_idempotent(lease, request, {"path": str(request.payload["path"]), "size_bytes": len(data)})
        if request.operation is EnvironmentOperation.ARTIFACT_WRITE:
            replay = self._replay_idempotent(lease, request)
            if replay is not None:
                return replay
            if self.artifact_store is None:
                raise LocalWorkspaceError("artifact store is not configured")
            encoded = request.payload.get("content_base64")
            if not isinstance(encoded, str):
                raise LocalWorkspaceError("artifact content_base64 is required")
            try:
                data = base64.b64decode(encoded, validate=True)
            except (ValueError, binascii.Error) as exc:
                raise LocalWorkspaceError("artifact content is not valid base64") from exc
            if len(data) > self.max_file_bytes:
                raise LocalWorkspaceError("artifact exceeds the workspace limit")
            ref = self.artifact_store.put_bytes(
                data,
                session_id=lease.environment_id,
                turn_id=str(request.payload.get("turn_id") or request.request_id),
                principal_id=self.principal_id,
                name=str(request.payload.get("name") or "artifact.bin"),
                mime_type=str(request.payload.get("mime_type") or "application/octet-stream"),
                producer="local_workspace",
                ref_id=request.idempotency_key,
            )
            return {"artifact": ref.to_dict()}
        raise EnvironmentPolicyDenied(f"local workspace operation is not supported: {request.operation.value}")

    def shutdown(self, lease: EnvironmentLease, *, reason: str) -> None:
        with self._lock:
            self._leases.pop(lease.lease_id, None)


__all__ = ["LocalWorkspaceError", "LocalWorkspaceTransport"]
