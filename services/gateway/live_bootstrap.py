"""Bootstrap the gateway with live scheduler/session state instead of proof files."""
from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from services.gateway.inference import InferenceEngine
from services.gateway.inference_backend import InferenceBackendError
from services.identity.threaded_resolver import SQLiteIdentityKeyResolver
from services.orchestrator.live_shared_backend import LiveSharedInferenceBackend
from services.orchestrator.live_shared_runtime import LIVE_SHARED_RUNTIME, LiveSharedRuntimeRegistry
from services.orchestrator.startup_recovery import RecoveryStateStore, reconcile_startup_state


def _int_env(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, str(default)))
    except ValueError as exc:
        raise InferenceBackendError(f"invalid {name}") from exc


def _float_env(name: str, default: float) -> float:
    try:
        return float(os.environ.get(name, str(default)))
    except ValueError as exc:
        raise InferenceBackendError(f"invalid {name}") from exc


def build_live_shared_backend_from_env(
    *, registry: LiveSharedRuntimeRegistry = LIVE_SHARED_RUNTIME,
) -> LiveSharedInferenceBackend:
    state_path = os.environ.get("COMPUTEMESH_ORCHESTRATOR_STATE_PATH", "").strip()
    identity_path = os.environ.get("COMPUTEMESH_IDENTITY_STATE_PATH", "").strip()
    llama_server = os.environ.get("COMPUTEMESH_LLAMA_SERVER_PATH", "").strip()
    work_root = os.environ.get("COMPUTEMESH_SHARED_WORK_ROOT", "").strip()
    if not state_path or not identity_path or not llama_server or not work_root:
        raise InferenceBackendError(
            "live shared inference requires COMPUTEMESH_ORCHESTRATOR_STATE_PATH, "
            "COMPUTEMESH_IDENTITY_STATE_PATH, COMPUTEMESH_LLAMA_SERVER_PATH and "
            "COMPUTEMESH_SHARED_WORK_ROOT"
        )
    if os.environ.get("COMPUTEMESH_ALLOW_EXPERIMENTAL_SHARED_PLACEMENT", "").strip() != "1":
        raise InferenceBackendError(
            "live shared M1 placement remains experimental; explicit opt-in is required"
        )
    forbidden = (
        "COMPUTEMESH_ORCHESTRATOR_PLACEMENT_DECISION",
        "COMPUTEMESH_ORCHESTRATOR_SHARED_RUN_EVIDENCE",
        "COMPUTEMESH_ORCHESTRATOR_EXECUTION_ATTESTATIONS",
    )
    if any(os.environ.get(name, "").strip() for name in forbidden):
        raise InferenceBackendError(
            "live shared bootstrap refuses pre-positioned placement/evidence/attestation files"
        )

    store = RecoveryStateStore(state_path)
    try:
        reconcile_startup_state(store)
        return LiveSharedInferenceBackend(
            registry=registry,
            store=store,
            resolver=SQLiteIdentityKeyResolver(identity_path),
            llama_server=Path(llama_server),
            work_root=Path(work_root),
            allow_experimental=True,
            lease_seconds=_int_env("COMPUTEMESH_ORCHESTRATOR_LEASE_SECONDS", 600),
            max_attempts=_int_env("COMPUTEMESH_LIVE_MAX_ATTEMPTS", 2),
            startup_timeout=_float_env("COMPUTEMESH_LIVE_STARTUP_TIMEOUT_SECONDS", 300.0),
            request_timeout=_float_env("COMPUTEMESH_LIVE_REQUEST_TIMEOUT_SECONDS", 300.0),
        )
    except Exception:
        store.close()
        raise


def install_live_shared_gateway(
    *,
    handler_cls: Any | None = None,
    registry: LiveSharedRuntimeRegistry = LIVE_SHARED_RUNTIME,
) -> LiveSharedInferenceBackend:
    if handler_cls is None:
        from services.gateway.server import GatewayHandler
        handler_cls = GatewayHandler
    backend = build_live_shared_backend_from_env(registry=registry)
    handler_cls.inference_engine = InferenceEngine(
        ledger=handler_cls.ledger,
        metrics=handler_cls.metrics,
        teaser_manager=handler_cls.teaser_manager,
        backend=backend,
    )
    return backend
