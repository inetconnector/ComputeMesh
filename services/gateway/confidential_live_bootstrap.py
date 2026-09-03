"""Install the complete ciphertext-only confidential path into the live gateway.

Protected mode is explicit opt-in. If enabled, every required durable/security
component is constructed before handler class state is changed; partial setup fails
startup rather than exposing a downgraded confidential route.
"""
from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path
import ssl
from typing import Any

from runtime.confidential.data_plane import PinnedHttpsConfidentialDataPlane
from runtime.confidential.replay_store import SQLiteConfidentialReplayStore
from runtime.confidential.session import SQLiteConfidentialSessionStore
from runtime.confidential.stream_data_plane import PinnedHttpsConfidentialStreamDataPlane
from services.gateway.confidential_coordinator import ConfidentialInferenceCoordinator
from services.orchestrator.live_shared_runtime import LiveSharedRuntimeRegistry
from services.orchestrator.remote_confidential_broker import (
    RemoteConfidentialSessionBroker,
    build_remote_confidential_broker_from_env,
)


class LiveConfidentialBootstrapError(RuntimeError):
    pass


@dataclass(frozen=True)
class LiveConfidentialRuntime:
    broker: RemoteConfidentialSessionBroker
    session_store: SQLiteConfidentialSessionStore
    replay_store: SQLiteConfidentialReplayStore
    coordinator: ConfidentialInferenceCoordinator
    data_plane: PinnedHttpsConfidentialDataPlane
    stream_data_plane: PinnedHttpsConfidentialStreamDataPlane


def _enabled() -> bool:
    return os.environ.get("COMPUTEMESH_CONFIDENTIAL_ENABLED", "").strip().lower() in {"1", "true", "yes", "on"}


def _required(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        raise LiveConfidentialBootstrapError(f"{name} is required when confidential mode is enabled")
    return value


def _float(name: str, default: float, *, minimum: float, maximum: float) -> float:
    try:
        value = float(os.environ.get(name, str(default)))
    except ValueError as exc:
        raise LiveConfidentialBootstrapError(f"{name} is invalid") from exc
    if not minimum <= value <= maximum:
        raise LiveConfidentialBootstrapError(f"{name} must be between {minimum} and {maximum}")
    return value


def _int(name: str, default: int, *, minimum: int, maximum: int) -> int:
    try:
        value = int(os.environ.get(name, str(default)))
    except ValueError as exc:
        raise LiveConfidentialBootstrapError(f"{name} is invalid") from exc
    if not minimum <= value <= maximum:
        raise LiveConfidentialBootstrapError(f"{name} must be between {minimum} and {maximum}")
    return value


def install_live_confidential_gateway(
    *,
    handler_cls: Any,
    registry: LiveSharedRuntimeRegistry,
) -> LiveConfidentialRuntime | None:
    """Atomically install protected admission/data-plane state on one handler class."""
    if not _enabled():
        handler_cls.confidential_coordinator = None
        handler_cls.confidential_replay_store = None
        handler_cls.confidential_data_plane = None
        handler_cls.confidential_stream_data_plane = None
        return None

    state_dir = Path(_required("COMPUTEMESH_CONFIDENTIAL_STATE_DIR"))
    state_dir.mkdir(parents=True, exist_ok=True)
    if not state_dir.is_dir():
        raise LiveConfidentialBootstrapError("COMPUTEMESH_CONFIDENTIAL_STATE_DIR is not a directory")

    try:
        broker = build_remote_confidential_broker_from_env(registry=registry)
        session_store = SQLiteConfidentialSessionStore(state_dir / "gateway_sessions.sqlite3")
        replay_store = SQLiteConfidentialReplayStore(state_dir / "gateway_replay.sqlite3")

        ca_file = os.environ.get("COMPUTEMESH_CONFIDENTIAL_DATA_PLANE_CA_FILE", "").strip() or None
        tls_context = ssl.create_default_context(cafile=ca_file)
        tls_context.minimum_version = ssl.TLSVersion.TLSv1_3
        timeout = _float(
            "COMPUTEMESH_CONFIDENTIAL_DATA_PLANE_TIMEOUT_SECONDS",
            120.0,
            minimum=0.1,
            maximum=600.0,
        )
        data_plane = PinnedHttpsConfidentialDataPlane(
            ssl_context=tls_context,
            timeout_seconds=timeout,
        )
        stream_data_plane = PinnedHttpsConfidentialStreamDataPlane(
            ssl_context=tls_context,
            timeout_seconds=timeout,
        )

        ledger = handler_cls.ledger
        owner_store = handler_cls.owner_account_store

        def provider_owner_resolver(provider_node_id: str) -> str:
            owner = owner_store.owner_for_provider_node(provider_node_id)
            if not owner:
                raise LiveConfidentialBootstrapError(
                    "selected confidential provider node has no durable owner binding"
                )
            return owner

        coordinator = ConfidentialInferenceCoordinator(
            ledger=ledger,
            session_store=session_store,
            broker=broker,
            provider_owner_resolver=provider_owner_resolver,
            marketplace_fee_bps=_int(
                "COMPUTEMESH_CONFIDENTIAL_MARKETPLACE_FEE_BPS",
                2500,
                minimum=0,
                maximum=10_000,
            ),
            self_compute_fee_bps=_int(
                "COMPUTEMESH_CONFIDENTIAL_SELF_COMPUTE_FEE_BPS",
                1000,
                minimum=1,
                maximum=10_000,
            ),
        )
        # Recover only after all dependencies exist. Invalid persisted receipts or
        # unresolved provider ownership fail startup instead of being skipped.
        coordinator.reconcile_metered(
            limit=_int("COMPUTEMESH_CONFIDENTIAL_RECOVERY_LIMIT", 100, minimum=1, maximum=10_000)
        )
    except LiveConfidentialBootstrapError:
        raise
    except Exception as exc:
        raise LiveConfidentialBootstrapError("confidential live bootstrap failed") from exc

    handler_cls.confidential_coordinator = coordinator
    handler_cls.confidential_replay_store = replay_store
    handler_cls.confidential_data_plane = data_plane
    handler_cls.confidential_stream_data_plane = stream_data_plane
    return LiveConfidentialRuntime(
        broker=broker,
        session_store=session_store,
        replay_store=replay_store,
        coordinator=coordinator,
        data_plane=data_plane,
        stream_data_plane=stream_data_plane,
    )
