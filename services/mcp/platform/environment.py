"""Bounded execution-environment contracts for the Agents Platform.

This module defines the policy boundary between an agent harness and a local
or mesh executor. It intentionally exposes typed operations only; there is no
generic command, shell or arbitrary remote-execution operation.
"""
from __future__ import annotations

import re
import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from pathlib import PurePosixPath
from typing import Any, Callable, Mapping, Protocol


class EnvironmentError(RuntimeError):
    """Base error for bounded environment lifecycle and execution failures."""


class EnvironmentStateConflict(EnvironmentError):
    """Raised when an environment lifecycle transition is invalid."""


class EnvironmentExpired(EnvironmentError):
    """Raised when a lease or maximum runtime has expired."""


class EnvironmentPolicyDenied(EnvironmentError):
    """Raised when an operation is outside the environment policy."""


class EnvironmentKind(str, Enum):
    NONE = "none"
    SELF_HOSTED = "self_hosted"
    MESH = "mesh"


class EnvironmentState(str, Enum):
    NEW = "new"
    PREPARING = "preparing"
    READY = "ready"
    RUNNING = "running"
    DRAINING = "draining"
    EXPIRED = "expired"
    REVOKED = "revoked"
    CLOSED = "closed"
    FAILED = "failed"


class EnvironmentOperation(str, Enum):
    HEALTH = "health"
    INFERENCE = "inference"
    TOOL_CALL = "tool_call"
    WORKSPACE_READ = "workspace_read"
    WORKSPACE_WRITE = "workspace_write"
    ARTIFACT_READ = "artifact_read"
    ARTIFACT_WRITE = "artifact_write"
    ARTIFACT_STAGE = "artifact_stage"
    ARTIFACT_STAGE_STATUS = "artifact_stage_status"

    @property
    def requires_idempotency(self) -> bool:
        return self in {
            EnvironmentOperation.TOOL_CALL,
            EnvironmentOperation.WORKSPACE_WRITE,
            EnvironmentOperation.ARTIFACT_WRITE,
            EnvironmentOperation.ARTIFACT_STAGE,
        }

    @property
    def writes_data(self) -> bool:
        return self in {
            EnvironmentOperation.WORKSPACE_WRITE,
            EnvironmentOperation.ARTIFACT_WRITE,
            EnvironmentOperation.ARTIFACT_STAGE,
        }


@dataclass(frozen=True)
class ResourceLimits:
    cpu_millis: int = 1000
    memory_bytes: int = 512 * 1024 * 1024
    vram_bytes: int = 0
    max_processes: int = 32
    max_runtime_seconds: int = 3600

    def __post_init__(self) -> None:
        if not 1 <= int(self.cpu_millis) <= 1_000_000:
            raise ValueError("cpu_millis must be between 1 and 1,000,000")
        if not 1 <= int(self.memory_bytes) <= 1 << 50:
            raise ValueError("memory_bytes is outside the supported bound")
        if not 0 <= int(self.vram_bytes) <= 1 << 50:
            raise ValueError("vram_bytes is outside the supported bound")
        if not 1 <= int(self.max_processes) <= 100_000:
            raise ValueError("max_processes must be between 1 and 100,000")
        if not 1 <= int(self.max_runtime_seconds) <= 7 * 24 * 3600:
            raise ValueError("max_runtime_seconds is outside the supported bound")


_IDENTIFIER = re.compile(r"^[A-Za-z0-9_.:-]{1,160}$")
_FORBIDDEN_PAYLOAD_KEYS = frozenset({"command", "cmd", "shell", "executable", "script", "remote_shell"})


@dataclass(frozen=True)
class EnvironmentSpec:
    environment_id: str
    session_id: str
    kind: EnvironmentKind = EnvironmentKind.MESH
    node_id: str | None = None
    model_id: str | None = None
    allowed_operations: frozenset[EnvironmentOperation] = frozenset({EnvironmentOperation.HEALTH, EnvironmentOperation.INFERENCE})
    allowed_paths: tuple[str, ...] = ()
    network_allowlist: tuple[str, ...] = ()
    resources: ResourceLimits = field(default_factory=ResourceLimits)
    lease_seconds: int = 300

    def __post_init__(self) -> None:
        for field_name in ("environment_id", "session_id"):
            value = str(getattr(self, field_name))
            if not _IDENTIFIER.fullmatch(value):
                raise ValueError(f"invalid {field_name}")
        if self.node_id is not None and not _IDENTIFIER.fullmatch(str(self.node_id)):
            raise ValueError("invalid node_id")
        if self.model_id is not None and not (1 <= len(str(self.model_id)) <= 256):
            raise ValueError("model_id must be 1..256 characters")
        operations = frozenset(EnvironmentOperation(operation) for operation in self.allowed_operations)
        object.__setattr__(self, "allowed_operations", operations)
        if not 1 <= int(self.lease_seconds) <= int(self.resources.max_runtime_seconds):
            raise ValueError("lease_seconds must fit within max_runtime_seconds")
        if len(self.allowed_paths) > 128 or len(self.network_allowlist) > 128:
            raise ValueError("environment allowlists are bounded to 128 entries")
        for path in self.allowed_paths:
            _validate_relative_path(path)
        for target in self.network_allowlist:
            if not 1 <= len(str(target)) <= 256:
                raise ValueError("network allowlist entry is invalid")
        if self.kind is EnvironmentKind.NONE and self.node_id is not None:
            raise ValueError("none environments cannot bind a node")


@dataclass(frozen=True)
class EnvironmentLease:
    lease_id: str
    environment_id: str
    issued_at: float
    expires_at: float
    revision: int = 1

    def validate(self, *, now: float, environment_id: str) -> None:
        if self.environment_id != environment_id:
            raise EnvironmentError("lease belongs to a different environment")
        if not _IDENTIFIER.fullmatch(self.lease_id):
            raise EnvironmentError("lease id is invalid")
        if self.expires_at <= now:
            raise EnvironmentExpired("environment lease has expired")
        if self.expires_at <= self.issued_at or self.revision < 1:
            raise EnvironmentError("lease contract is invalid")


@dataclass(frozen=True)
class EnvironmentRequest:
    request_id: str
    operation: EnvironmentOperation
    payload: Mapping[str, Any] = field(default_factory=dict)
    idempotency_key: str | None = None

    def __post_init__(self) -> None:
        if not _IDENTIFIER.fullmatch(str(self.request_id)):
            raise ValueError("invalid environment request_id")
        object.__setattr__(self, "operation", EnvironmentOperation(self.operation))
        if not isinstance(self.payload, Mapping):
            raise ValueError("environment request payload must be an object")
        if len(str(self.payload)) > 256_000:
            raise ValueError("environment request payload is too large")
        forbidden = _FORBIDDEN_PAYLOAD_KEYS & {str(key).lower() for key in self.payload}
        if forbidden:
            raise EnvironmentPolicyDenied("generic shell/command payloads are not supported")
        if self.operation.requires_idempotency:
            if not self.idempotency_key or not _IDENTIFIER.fullmatch(str(self.idempotency_key)):
                raise EnvironmentPolicyDenied("side-effecting environment requests require an idempotency key")


class EnvironmentTransport(Protocol):
    """Authenticated transport contract implemented by NodeOS adapters."""

    def prepare(self, spec: EnvironmentSpec) -> EnvironmentLease: ...

    def heartbeat(self, lease: EnvironmentLease) -> EnvironmentLease: ...

    def execute(self, lease: EnvironmentLease, request: EnvironmentRequest) -> Mapping[str, Any]: ...

    def shutdown(self, lease: EnvironmentLease, *, reason: str) -> None: ...


class EnvironmentEventSink(Protocol):
    def __call__(self, event_type: str, payload: Mapping[str, Any]) -> None: ...


def _validate_relative_path(value: str) -> None:
    path = str(value)
    if not path or len(path) > 512 or "\\" in path:
        raise ValueError("paths must be bounded POSIX-relative paths")
    parsed = PurePosixPath(path)
    if parsed.is_absolute() or ".." in parsed.parts or "." in parsed.parts:
        raise ValueError("path allowlist entries must not escape the workspace")


class BoundedEnvironmentExecutor:
    """Lifecycle and policy boundary around an authenticated environment transport."""

    def __init__(
        self,
        spec: EnvironmentSpec,
        *,
        transport: EnvironmentTransport | None = None,
        event_sink: EnvironmentEventSink | None = None,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self.spec = spec
        self.transport = transport
        self.event_sink = event_sink
        self.clock = clock
        self.state = EnvironmentState.NEW
        self.lease: EnvironmentLease | None = None
        self._started_at: float | None = None

        if self.spec.kind is EnvironmentKind.NONE and transport is not None:
            raise ValueError("none environments cannot have an execution transport")
        if self.spec.kind is not EnvironmentKind.NONE and transport is None:
            raise ValueError("self_hosted and mesh environments require a transport")

    def _emit(self, event_type: str, **payload: Any) -> None:
        if self.event_sink is not None:
            self.event_sink(event_type, {
                "environment_id": self.spec.environment_id,
                "session_id": self.spec.session_id,
                **payload,
            })

    def _ensure_runtime_valid(self) -> None:
        now = float(self.clock())
        if self._started_at is not None and now - self._started_at >= self.spec.resources.max_runtime_seconds:
            self.state = EnvironmentState.EXPIRED
            self._emit("environment.expired", reason="max_runtime")
            raise EnvironmentExpired("environment maximum runtime has expired")
        if self.lease is not None:
            try:
                self.lease.validate(now=now, environment_id=self.spec.environment_id)
            except EnvironmentExpired:
                self.state = EnvironmentState.EXPIRED
                self._emit("environment.expired", reason="lease")
                raise

    def prepare(self) -> EnvironmentState:
        if self.state is not EnvironmentState.NEW:
            raise EnvironmentStateConflict(f"cannot prepare environment in state {self.state.value}")
        self.state = EnvironmentState.PREPARING
        self._started_at = float(self.clock())
        self._emit("environment.prepare.started", kind=self.spec.kind.value, node_id=self.spec.node_id)
        try:
            if self.spec.kind is EnvironmentKind.NONE:
                self.state = EnvironmentState.READY
            else:
                assert self.transport is not None
                lease = self.transport.prepare(self.spec)
                lease.validate(now=float(self.clock()), environment_id=self.spec.environment_id)
                self.lease = lease
                self.state = EnvironmentState.READY
        except Exception:
            self.state = EnvironmentState.FAILED
            self._emit("environment.prepare.failed")
            raise
        self._emit("environment.ready", lease_id=self.lease.lease_id if self.lease else None)
        return self.state

    def heartbeat(self) -> EnvironmentLease | None:
        if self.state not in {EnvironmentState.READY, EnvironmentState.RUNNING}:
            raise EnvironmentStateConflict(f"cannot heartbeat environment in state {self.state.value}")
        self._ensure_runtime_valid()
        if self.spec.kind is EnvironmentKind.NONE:
            self._emit("environment.heartbeat", lease_id=None)
            return None
        assert self.transport is not None and self.lease is not None
        renewed = self.transport.heartbeat(self.lease)
        renewed.validate(now=float(self.clock()), environment_id=self.spec.environment_id)
        if renewed.revision <= self.lease.revision:
            raise EnvironmentError("heartbeat did not advance the lease revision")
        self.lease = renewed
        self._emit("environment.heartbeat", lease_id=renewed.lease_id, lease_revision=renewed.revision)
        return renewed

    def _validate_request_policy(self, request: EnvironmentRequest) -> None:
        if request.operation not in self.spec.allowed_operations:
            raise EnvironmentPolicyDenied(f"operation is not allowed: {request.operation.value}")
        if request.operation in {
            EnvironmentOperation.WORKSPACE_READ,
            EnvironmentOperation.WORKSPACE_WRITE,
            EnvironmentOperation.ARTIFACT_STAGE,
            EnvironmentOperation.ARTIFACT_STAGE_STATUS,
        } and "path" in request.payload:
            path = str(request.payload["path"])
            _validate_relative_path(path)
            if self.spec.allowed_paths and not any(path == allowed or path.startswith(allowed.rstrip("/") + "/") for allowed in self.spec.allowed_paths):
                raise EnvironmentPolicyDenied("path is outside the environment allowlist")
        if "network_target" in request.payload:
            target = str(request.payload["network_target"])
            if target not in self.spec.network_allowlist:
                raise EnvironmentPolicyDenied("network target is outside the environment allowlist")

    def execute(self, request: EnvironmentRequest) -> Mapping[str, Any]:
        if self.state not in {EnvironmentState.READY, EnvironmentState.RUNNING}:
            raise EnvironmentStateConflict(f"cannot execute environment request in state {self.state.value}")
        self._ensure_runtime_valid()
        self._validate_request_policy(request)
        self._emit("environment.operation.requested", operation=request.operation.value, request_id=request.request_id)
        if self.spec.kind is EnvironmentKind.NONE:
            raise EnvironmentPolicyDenied("none environments do not execute environment operations")
        assert self.transport is not None and self.lease is not None
        self.state = EnvironmentState.RUNNING
        try:
            result = self.transport.execute(self.lease, request)
            if not isinstance(result, Mapping):
                raise EnvironmentError("environment transport returned a non-object result")
        except Exception:
            self.state = EnvironmentState.FAILED
            self._emit("environment.operation.failed", operation=request.operation.value, request_id=request.request_id)
            raise
        else:
            self.state = EnvironmentState.READY
            self._emit("environment.operation.completed", operation=request.operation.value, request_id=request.request_id)
            return dict(result)

    def shutdown(self, *, reason: str = "normal_shutdown") -> EnvironmentState:
        if self.state is EnvironmentState.CLOSED:
            return self.state
        if not 1 <= len(str(reason)) <= 256:
            raise ValueError("shutdown reason must be 1..256 characters")
        prior = self.state
        self.state = EnvironmentState.DRAINING
        self._emit("environment.draining", reason=reason, prior_state=prior.value)
        try:
            if self.lease is not None and self.transport is not None:
                self.transport.shutdown(self.lease, reason=reason)
        except Exception:
            self.state = EnvironmentState.FAILED
            self._emit("environment.shutdown.failed", reason=reason)
            raise
        self.state = EnvironmentState.CLOSED
        self._emit("environment.closed", reason=reason)
        return self.state

    def revoke(self, *, reason: str = "revoked") -> EnvironmentState:
        if not 1 <= len(str(reason)) <= 256:
            raise ValueError("revocation reason must be 1..256 characters")
        if self.state in {EnvironmentState.CLOSED, EnvironmentState.REVOKED}:
            return self.state
        try:
            if self.lease is not None and self.transport is not None:
                self.transport.shutdown(self.lease, reason=reason)
        finally:
            self.state = EnvironmentState.REVOKED
            self._emit("environment.revoked", reason=reason)
        return self.state


def new_request_id(prefix: str = "envreq") -> str:
    """Create a bounded request identifier for callers without one."""
    return f"{prefix}_{uuid.uuid4().hex}"
