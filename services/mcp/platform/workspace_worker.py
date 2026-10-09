"""Private JSONL child for :mod:`process_workspace`.

This module is launched with an argument list, never through a shell. It owns
the local workspace transport so filesystem operations do not run in the
parent's agent process.
"""
from __future__ import annotations

import argparse
import json
import math
import os
from typing import Any, Mapping

from .environment import (
    EnvironmentKind,
    EnvironmentLease,
    EnvironmentOperation,
    EnvironmentRequest,
    EnvironmentSpec,
    ResourceLimits,
)
from .process_workspace import _lease_payload
from .workspace import LocalWorkspaceTransport


def _apply_posix_limits(*, memory_bytes: int, max_runtime_seconds: int, max_processes: int) -> None:
    if os.name == "nt":
        return
    try:
        import resource

        cpu_seconds = max(1, int(math.ceil(float(max_runtime_seconds))))
        resource.setrlimit(resource.RLIMIT_CPU, (cpu_seconds, cpu_seconds + 1))
        resource.setrlimit(resource.RLIMIT_AS, (int(memory_bytes), int(memory_bytes)))
        if hasattr(resource, "RLIMIT_FSIZE"):
            resource.setrlimit(resource.RLIMIT_FSIZE, (int(memory_bytes), int(memory_bytes)))
    except (OSError, ValueError):
        # The parent still enforces protocol and wall-clock bounds. Some
        # containerized hosts prohibit individual rlimit changes.
        return


def _spec(raw: Any) -> EnvironmentSpec:
    if not isinstance(raw, Mapping):
        raise ValueError("spec must be an object")
    resources = raw.get("resources")
    if not isinstance(resources, Mapping):
        raise ValueError("spec resources must be an object")
    return EnvironmentSpec(
        environment_id=str(raw["environment_id"]),
        session_id=str(raw["session_id"]),
        kind=EnvironmentKind(str(raw["kind"])),
        node_id=(str(raw["node_id"]) if raw.get("node_id") is not None else None),
        model_id=(str(raw["model_id"]) if raw.get("model_id") is not None else None),
        allowed_operations=frozenset(EnvironmentOperation(value) for value in raw["allowed_operations"]),
        allowed_paths=tuple(str(value) for value in raw["allowed_paths"]),
        network_allowlist=tuple(str(value) for value in raw["network_allowlist"]),
        resources=ResourceLimits(
            cpu_millis=int(resources["cpu_millis"]),
            memory_bytes=int(resources["memory_bytes"]),
            vram_bytes=int(resources["vram_bytes"]),
            max_processes=int(resources["max_processes"]),
            max_runtime_seconds=int(resources["max_runtime_seconds"]),
        ),
        lease_seconds=int(raw["lease_seconds"]),
    )


def _lease(raw: Any) -> EnvironmentLease:
    if not isinstance(raw, Mapping):
        raise ValueError("lease must be an object")
    return EnvironmentLease(
        lease_id=str(raw["lease_id"]),
        environment_id=str(raw["environment_id"]),
        issued_at=float(raw["issued_at"]),
        expires_at=float(raw["expires_at"]),
        revision=int(raw["revision"]),
    )


def _request(raw: Any) -> EnvironmentRequest:
    if not isinstance(raw, Mapping):
        raise ValueError("request must be an object")
    payload = raw.get("payload")
    if not isinstance(payload, Mapping):
        raise ValueError("request payload must be an object")
    return EnvironmentRequest(
        request_id=str(raw["request_id"]),
        operation=EnvironmentOperation(str(raw["operation"])),
        payload=dict(payload),
        idempotency_key=(str(raw["idempotency_key"]) if raw.get("idempotency_key") is not None else None),
    )


def _write(value: Mapping[str, Any], max_message_bytes: int = 4 * 1024 * 1024) -> None:
    encoded = json.dumps(value, ensure_ascii=False, separators=(",", ":"), default=str)
    if len(encoded.encode("utf-8")) > max_message_bytes:
        encoded = json.dumps({"ok": False, "error": "workspace response exceeds the message limit"})
    print(encoded, flush=True)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--root", required=True)
    parser.add_argument("--max-file-bytes", type=int, required=True)
    parser.add_argument("--max-runtime-seconds", type=int, required=True)
    parser.add_argument("--memory-bytes", type=int, required=True)
    parser.add_argument("--max-processes", type=int, required=True)
    parser.add_argument("--allow-mesh", action="store_true")
    args = parser.parse_args(argv)
    _apply_posix_limits(
        memory_bytes=args.memory_bytes,
        max_runtime_seconds=args.max_runtime_seconds,
        max_processes=args.max_processes,
    )
    transport = LocalWorkspaceTransport(
        args.root,
        max_file_bytes=args.max_file_bytes,
        allow_mesh=args.allow_mesh,
    )
    for line in __import__("sys").stdin:
        try:
            message = json.loads(line)
            if not isinstance(message, Mapping):
                raise ValueError("message must be an object")
            operation = str(message.get("operation") or "")
            payload = message.get("payload")
            if not isinstance(payload, Mapping):
                raise ValueError("message payload must be an object")
            if operation == "prepare":
                lease = transport.prepare(_spec(payload.get("spec")))
                result = {"lease": _lease_payload(lease)}
            elif operation == "heartbeat":
                lease = transport.heartbeat(_lease(payload.get("lease")))
                result = {"lease": _lease_payload(lease)}
            elif operation == "execute":
                result = {"result": dict(transport.execute(_lease(payload.get("lease")), _request(payload.get("request"))))}
            elif operation == "shutdown":
                transport.shutdown(_lease(payload.get("lease")), reason=str(payload.get("reason") or "shutdown"))
                _write({"ok": True, "result": {}})
                return 0
            elif operation == "close":
                return 0
            else:
                raise ValueError("unsupported workspace operation")
            _write({"ok": True, "result": result})
        except Exception as exc:
            _write({"ok": False, "error": f"{type(exc).__name__}: {exc}"})
    return 0


if __name__ == "__main__":  # pragma: no cover - exercised through the parent transport
    raise SystemExit(main())
