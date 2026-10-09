"""Bounded local executor for authenticated NodeOS mesh environments.

This adapter exposes only the typed environment operations. It deliberately
does not turn the provider into a remote shell: filesystem work is delegated
to the existing symlink-safe workspace transport and inference is delegated
to the explicitly configured local model backend.
"""
from __future__ import annotations

import base64
import binascii
import hashlib
import inspect
import os
import threading
import time
from dataclasses import dataclass
from pathlib import PurePosixPath
from typing import Any, Callable, Mapping

from protocol.node_session import SessionSnapshot
from services.mcp.platform.environment import (
    EnvironmentKind,
    EnvironmentLease,
    EnvironmentOperation,
    EnvironmentPolicyDenied,
    EnvironmentRequest,
    EnvironmentSpec,
    ResourceLimits,
)
from services.mcp.platform.workspace import LocalWorkspaceTransport


class NodeEnvironmentError(RuntimeError):
    """Raised when a NodeOS environment request cannot be executed."""


@dataclass(frozen=True)
class _EnvironmentRecord:
    spec: EnvironmentSpec
    lease: EnvironmentLease


class NodeEnvironmentExecutor:
    """Execute bounded mesh environment operations on one provider node."""

    def __init__(
        self,
        *,
        node_id: str,
        root: str,
        inference_executor: Callable[[SessionSnapshot, Mapping[str, Any]], Mapping[str, Any]] | None = None,
        artifact_store: Any | None = None,
        max_file_bytes: int = 8 * 1024 * 1024,
        clock: Callable[[], float] = time.time,
    ) -> None:
        if not node_id:
            raise ValueError("node_id is required")
        self.node_id = node_id
        self.clock = clock
        self.inference_executor = inference_executor
        self.workspace = LocalWorkspaceTransport(
            root,
            artifact_store=artifact_store,
            principal_id=node_id,
            max_file_bytes=max_file_bytes,
            allow_mesh=True,
            clock=clock,
        )
        self._lock = threading.RLock()
        self._environments: dict[str, _EnvironmentRecord] = {}
        self._stage_idempotency: dict[tuple[str, str], tuple[str, dict[str, Any]]] = {}

    def __call__(
        self,
        session: SessionSnapshot,
        payload: Mapping[str, Any],
        cancel_event: Any | None = None,
    ) -> Mapping[str, Any]:
        operation = str(payload.get("operation") or "")
        if operation == "prepare":
            return self._prepare(session, payload)
        if operation in {"heartbeat", "execute", "shutdown"}:
            return self._existing_operation(session, payload, operation, cancel_event=cancel_event)
        raise NodeEnvironmentError("unsupported environment lifecycle operation")

    def _prepare(self, session: SessionSnapshot, payload: Mapping[str, Any]) -> Mapping[str, Any]:
        raw_spec = payload.get("spec")
        if not isinstance(raw_spec, Mapping):
            raise NodeEnvironmentError("environment prepare requires a spec")
        spec = self._spec_from_payload(session, payload, raw_spec)
        with self._lock:
            existing = self._environments.get(spec.environment_id)
            if existing is not None:
                if existing.spec != spec:
                    raise NodeEnvironmentError("environment id is already bound to a different spec")
                lease = existing.lease
                return self._lease_result(lease, idempotency_replay=True)
        lease = self.workspace.prepare(spec)
        with self._lock:
            self._environments[spec.environment_id] = _EnvironmentRecord(spec, lease)
        return self._lease_result(lease)

    def _existing_operation(
        self,
        session: SessionSnapshot,
        payload: Mapping[str, Any],
        operation: str,
        *,
        cancel_event: Any | None = None,
    ) -> Mapping[str, Any]:
        environment_id = str(payload.get("environment_id") or "")
        lease_id = str(payload.get("lease_id") or "")
        if not environment_id or not lease_id:
            raise NodeEnvironmentError("environment operation requires environment and lease IDs")
        with self._lock:
            record = self._environments.get(environment_id)
        if record is None or record.lease.lease_id != lease_id:
            raise NodeEnvironmentError("environment lease is unknown")
        requested_revision = payload.get("lease_revision")
        if requested_revision != record.lease.revision:
            raise NodeEnvironmentError("environment lease revision mismatch")
        if (
            record.spec.session_id != session.session_id
            or record.spec.node_id != self.node_id
            or session.node_id != self.node_id
        ):
            raise NodeEnvironmentError("environment session or node binding mismatch")

        if operation == "heartbeat":
            renewed = self.workspace.heartbeat(record.lease)
            with self._lock:
                self._environments[environment_id] = _EnvironmentRecord(record.spec, renewed)
            return self._lease_result(renewed)
        if operation == "shutdown":
            self.workspace.shutdown(record.lease, reason=str(payload.get("reason") or "shutdown"))
            with self._lock:
                self._environments.pop(environment_id, None)
            return {"status": "ok"}
        return self._execute(session, record, payload, cancel_event=cancel_event)

    def _execute(
        self,
        session: SessionSnapshot,
        record: _EnvironmentRecord,
        payload: Mapping[str, Any],
        *,
        cancel_event: Any | None = None,
    ) -> Mapping[str, Any]:
        operation_name = str(payload.get("operation_name") or "")
        try:
            operation = EnvironmentOperation(operation_name)
        except ValueError as exc:
            raise NodeEnvironmentError("environment operation name is invalid") from exc
        request_payload = payload.get("payload")
        if not isinstance(request_payload, Mapping):
            raise NodeEnvironmentError("environment execute requires an object payload")
        request = EnvironmentRequest(
            request_id=str(payload.get("request_id") or ""),
            operation=operation,
            payload=dict(request_payload),
            idempotency_key=(str(payload["idempotency_key"]) if payload.get("idempotency_key") is not None else None),
        )
        self._validate_policy(record.spec, request)
        if operation is EnvironmentOperation.INFERENCE:
            if self.inference_executor is None:
                raise NodeEnvironmentError("local inference executor is not configured")
            inference_request = dict(request.payload)
            requested_model = inference_request.get("model_id")
            if record.spec.model_id is not None and requested_model is not None and str(requested_model) != record.spec.model_id:
                raise NodeEnvironmentError("inference model does not match the environment binding")
            model_id = str(requested_model or record.spec.model_id or "")
            if not model_id:
                raise NodeEnvironmentError("inference requires a model binding")
            inference_request["model_id"] = model_id
            inference_request.setdefault("session_id", session.session_id)
            inference_request.setdefault("turn_id", str(inference_request.get("turn_id") or request.request_id))
            inference_request["lease_id"] = record.lease.lease_id
            if cancel_event is not None and _accepts_cancel_token(self.inference_executor):
                result = self.inference_executor(session, inference_request, cancel_event)
            else:
                result = self.inference_executor(session, inference_request)
        elif operation in {EnvironmentOperation.ARTIFACT_STAGE, EnvironmentOperation.ARTIFACT_STAGE_STATUS}:
            result = self._stage_artifact(record, request)
        else:
            result = self.workspace.execute(record.lease, request)
        if not isinstance(result, Mapping):
            raise NodeEnvironmentError("environment operation returned a non-object result")
        return {"result": dict(result)}

    @staticmethod
    def _spec_from_payload(
        session: SessionSnapshot,
        payload: Mapping[str, Any],
        raw: Mapping[str, Any],
    ) -> EnvironmentSpec:
        try:
            resources_raw = raw["resources"]
            if not isinstance(resources_raw, Mapping):
                raise TypeError("resources")
            allowed = frozenset(EnvironmentOperation(value) for value in raw["allowed_operations"])
            spec = EnvironmentSpec(
                environment_id=str(payload["environment_id"]),
                session_id=session.session_id,
                kind=EnvironmentKind(raw["kind"]),
                node_id=str(payload["node_id"]),
                model_id=(str(raw["model_id"]) if raw.get("model_id") is not None else None),
                allowed_operations=allowed,
                allowed_paths=tuple(str(value) for value in raw["allowed_paths"]),
                network_allowlist=tuple(str(value) for value in raw["network_allowlist"]),
                resources=ResourceLimits(**{key: int(resources_raw[key]) for key in (
                    "cpu_millis", "memory_bytes", "vram_bytes", "max_processes", "max_runtime_seconds"
                )}),
                lease_seconds=int(raw["lease_seconds"]),
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise NodeEnvironmentError("environment spec is invalid") from exc
        if spec.kind is not EnvironmentKind.MESH or spec.node_id != str(payload["node_id"]):
            raise NodeEnvironmentError("NodeOS executor accepts only mesh environments for its own node")
        if spec.node_id != str(getattr(session, "node_id", "")):
            raise NodeEnvironmentError("environment spec targets another node")
        return spec

    @staticmethod
    def _validate_policy(spec: EnvironmentSpec, request: EnvironmentRequest) -> None:
        if request.operation not in spec.allowed_operations:
            raise EnvironmentPolicyDenied(f"operation is not allowed: {request.operation.value}")
        if request.operation in {
            EnvironmentOperation.WORKSPACE_READ,
            EnvironmentOperation.WORKSPACE_WRITE,
            EnvironmentOperation.ARTIFACT_STAGE,
            EnvironmentOperation.ARTIFACT_STAGE_STATUS,
        }:
            raw_path = str(request.payload.get("path") or "")
            parsed = PurePosixPath(raw_path)
            if not raw_path or parsed.is_absolute() or ".." in parsed.parts or "." in parsed.parts or "\\" in raw_path:
                raise EnvironmentPolicyDenied("workspace path escapes the environment")
            if spec.allowed_paths and not any(
                raw_path == allowed or raw_path.startswith(allowed.rstrip("/") + "/")
                for allowed in spec.allowed_paths
            ):
                raise EnvironmentPolicyDenied("workspace path is outside the environment allowlist")
        if "network_target" in request.payload and str(request.payload["network_target"]) not in spec.network_allowlist:
            raise EnvironmentPolicyDenied("network target is outside the environment allowlist")

    def _stage_artifact(self, record: _EnvironmentRecord, request: EnvironmentRequest) -> dict[str, Any]:
        """Receive one verified artifact chunk and commit it atomically."""
        payload = request.payload
        path_value = str(payload.get("path") or "")
        digest = str(payload.get("artifact_id") or "")
        total_bytes = payload.get("total_bytes")
        if not digest.startswith("sha256:") or len(digest) != len("sha256:") + 64:
            raise NodeEnvironmentError("artifact stage requires a sha256 artifact id")
        try:
            int(digest.removeprefix("sha256:"), 16)
            total = int(total_bytes)
        except (TypeError, ValueError):
            raise NodeEnvironmentError("artifact stage metadata is invalid") from None
        if total < 0 or total > self.workspace.max_file_bytes:
            raise NodeEnvironmentError("artifact exceeds the node workspace limit")

        workspace = self.workspace._lease_workspace(record.lease)
        target = self.workspace._safe_path(workspace, path_value)
        digest_hex = digest.removeprefix("sha256:")
        temporary = target.with_name(f".{target.name}.computemesh-{digest_hex}.part")
        if request.operation is EnvironmentOperation.ARTIFACT_STAGE_STATUS:
            return self._stage_status(path_value, target, temporary, digest_hex, total)

        if not request.idempotency_key:
            raise NodeEnvironmentError("artifact stage requires an idempotency key")
        encoded = payload.get("content_base64")
        if not isinstance(encoded, str):
            raise NodeEnvironmentError("artifact stage content_base64 is required")
        try:
            data = base64.b64decode(encoded, validate=True)
        except (ValueError, binascii.Error) as exc:
            raise NodeEnvironmentError("artifact stage content is not valid base64") from exc
        offset = payload.get("offset")
        try:
            offset = int(offset)
        except (TypeError, ValueError):
            raise NodeEnvironmentError("artifact stage offset is invalid") from None
        if offset < 0 or offset + len(data) > total:
            raise NodeEnvironmentError("artifact stage chunk is outside the artifact")
        if len(data) == 0 and not (total == 0 and offset == 0 and bool(payload.get("final"))):
            raise NodeEnvironmentError("artifact stage chunks must not be empty")

        encoded_request = repr((path_value, digest, total, offset, encoded, bool(payload.get("final")), bool(payload.get("overwrite"))))
        key = (record.spec.environment_id, request.idempotency_key)
        with self._lock:
            prior = self._stage_idempotency.get(key)
            if prior is not None:
                if prior[0] != encoded_request:
                    raise NodeEnvironmentError("artifact stage idempotency key was reused with different data")
                return dict(prior[1], idempotency_replay=True)

        target.parent.mkdir(parents=True, exist_ok=True)
        with self._lock:
            if temporary.is_symlink():
                raise NodeEnvironmentError("artifact staging path is a symlink")
            current = temporary.stat().st_size if temporary.exists() else 0
            if current != offset:
                raise NodeEnvironmentError(f"artifact stage offset mismatch: expected {current}, got {offset}")
            if offset == 0:
                if target.exists() and not bool(payload.get("overwrite", False)):
                    raise NodeEnvironmentError("workspace file already exists")
                temporary.unlink(missing_ok=True)
            with temporary.open("ab") as handle:
                handle.write(data)
                handle.flush()
                os.fsync(handle.fileno())
            next_offset = offset + len(data)
            final = bool(payload.get("final"))
            if final:
                if next_offset != total:
                    raise NodeEnvironmentError("final artifact stage chunk does not complete the artifact")
                with temporary.open("rb") as handle:
                    actual = hashlib.sha256(handle.read()).hexdigest()
                if actual != digest_hex:
                    raise NodeEnvironmentError("artifact digest verification failed")
                os.replace(temporary, target)
                result = {"path": path_value, "size_bytes": total, "next_offset": total, "complete": True, "artifact_id": digest}
            else:
                result = {"path": path_value, "size_bytes": total, "next_offset": next_offset, "complete": False, "artifact_id": digest}
            self._stage_idempotency[key] = (encoded_request, dict(result))
            return dict(result)

    @staticmethod
    def _stage_status(path_value: str, target: Any, temporary: Any, digest_hex: str, total: int) -> dict[str, Any]:
        if target.is_file():
            with target.open("rb") as handle:
                complete = target.stat().st_size == total and hashlib.sha256(handle.read()).hexdigest() == digest_hex
            if complete:
                return {"path": path_value, "artifact_id": "sha256:" + digest_hex, "size_bytes": total, "next_offset": total, "complete": True}
        next_offset = temporary.stat().st_size if temporary.is_file() else 0
        if next_offset > total:
            raise NodeEnvironmentError("staged artifact exceeds declared size")
        return {"path": path_value, "artifact_id": "sha256:" + digest_hex, "size_bytes": total, "next_offset": next_offset, "complete": False}

    @staticmethod
    def _lease_result(lease: EnvironmentLease, *, idempotency_replay: bool = False) -> dict[str, Any]:
        result: dict[str, Any] = {
            "lease_id": lease.lease_id,
            "issued_at": lease.issued_at,
            "expires_at": lease.expires_at,
            "lease_revision": lease.revision,
        }
        if idempotency_replay:
            result["idempotency_replay"] = True
        return result


__all__ = ["NodeEnvironmentError", "NodeEnvironmentExecutor"]


def _accepts_cancel_token(handler: Callable[..., Any] | None) -> bool:
    if handler is None:
        return False
    try:
        parameters = inspect.signature(handler).parameters.values()
    except (TypeError, ValueError):
        return False
    positional = [
        parameter for parameter in parameters
        if parameter.kind in {inspect.Parameter.POSITIONAL_ONLY, inspect.Parameter.POSITIONAL_OR_KEYWORD}
    ]
    return len(positional) >= 3 or any(
        parameter.kind is inspect.Parameter.VAR_POSITIONAL
        for parameter in parameters
    )
