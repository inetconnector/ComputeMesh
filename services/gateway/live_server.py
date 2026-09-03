"""Run the canonical ComputeMesh live gateway.

The production entry point is one HTTP server combining OpenAI compatibility,
unified-owner accounting, cancellation and internal ciphertext-only protected
transport. It never starts a second user-facing confidential API.
"""
from __future__ import annotations

import argparse
from http.server import ThreadingHTTPServer
import importlib
import os
from pathlib import Path
import sys
from typing import Callable

from protocol.node_identity import Ed25519ChallengeVerifier
from services.billing.threadsafe_ledger import SynchronizedLedgerProxy
from services.compliance.policy import assert_production_launch_gate
from services.gateway.cancellable_owner_inference import CancellableUnifiedOwnerInferenceEngine
from services.gateway.confidential_live_bootstrap import (
    LiveConfidentialRuntime,
    install_live_confidential_gateway,
)
from services.gateway.gpu_promo_dispatch_runtime import (
    RunningGpuPromoDispatch,
    start_optional_gpu_promo_dispatch,
)
from services.gateway.live_bootstrap import build_live_shared_backend_from_env
from services.gateway.server import DEFAULT_PORT
from services.gateway.unified_live_handler import build_unified_live_protected_handler
from services.identity.threaded_resolver import SQLiteIdentityKeyResolver
from services.orchestrator.live_control_plane import IntegratedLiveControlPlane
from services.orchestrator.live_model_catalog import register_verified_live_models
from services.orchestrator.live_shared_runtime import LIVE_SHARED_RUNTIME, LiveSharedRuntimeRegistry
from services.orchestrator.settlement_recovery import (
    reconcile_completed_settlements,
    replay_billing_outbox,
)


class LiveGatewayBootstrapError(RuntimeError):
    pass


def configure_live_runtime_from_module(
    module_name: str,
    *,
    registry: LiveSharedRuntimeRegistry = LIVE_SHARED_RUNTIME,
) -> None:
    if not module_name:
        return
    if len(module_name) > 256:
        raise LiveGatewayBootstrapError("control module name is too long")
    module = importlib.import_module(module_name)
    configure: Callable[[LiveSharedRuntimeRegistry], None] | None = getattr(
        module, "configure_computemesh_live_runtime", None
    )
    if configure is None or not callable(configure):
        raise LiveGatewayBootstrapError(
            "control module must export configure_computemesh_live_runtime(registry)"
        )
    configure(registry)


def _load_models_from_env(registry: LiveSharedRuntimeRegistry) -> tuple[str, ...]:
    catalog = os.environ.get("COMPUTEMESH_LIVE_MODEL_CATALOG", "").strip()
    root = os.environ.get("COMPUTEMESH_LIVE_MODEL_ROOT", "").strip()
    if not catalog or not root:
        raise LiveGatewayBootstrapError(
            "live serving requires COMPUTEMESH_LIVE_MODEL_CATALOG and COMPUTEMESH_LIVE_MODEL_ROOT"
        )
    return register_verified_live_models(
        registry,
        catalog_path=Path(catalog),
        catalog_root=Path(root),
    )


def _start_integrated_control_plane(
    *,
    registry: LiveSharedRuntimeRegistry,
    host: str,
    port: int,
    cert_file: str,
    key_file: str,
    identity_path: str,
) -> IntegratedLiveControlPlane:
    if not cert_file or not key_file or not identity_path:
        raise LiveGatewayBootstrapError(
            "automatic provider registration requires control TLS cert/key and COMPUTEMESH_IDENTITY_STATE_PATH"
        )
    plane = IntegratedLiveControlPlane(
        registry=registry,
        verifier=Ed25519ChallengeVerifier(SQLiteIdentityKeyResolver(identity_path)),
        host=host,
        port=port,
        cert_file=cert_file,
        key_file=key_file,
    )
    plane.start()
    return plane


def _synchronize_live_ledger(handler_cls):
    current = handler_cls.ledger
    if isinstance(current, SynchronizedLedgerProxy):
        return current
    proxy = SynchronizedLedgerProxy(current)
    handler_cls.ledger = proxy
    if getattr(handler_cls, "stripe_svc", None) is not None:
        handler_cls.stripe_svc.ledger = proxy
    executor = getattr(handler_cls, "settlement_executor", None)
    if executor is not None and hasattr(executor, "ledger"):
        executor.ledger = proxy
    sync = getattr(handler_cls, "sync_subsystems", None)
    if callable(sync):
        sync()
    return proxy


def _install_cancellable_live_gateway(handler_cls):
    """Install the live backend without replacing unified-owner accounting."""
    ledger = _synchronize_live_ledger(handler_cls)
    backend = build_live_shared_backend_from_env(registry=LIVE_SHARED_RUNTIME)
    replay_billing_outbox(backend.store, ledger)
    reconcile_completed_settlements(backend.store, ledger)
    handler_cls.inference_engine = CancellableUnifiedOwnerInferenceEngine(
        ledger=ledger,
        owner_account_store=handler_cls.owner_account_store,
        metrics=handler_cls.metrics,
        teaser_manager=handler_cls.teaser_manager,
        backend=backend,
    )
    return backend


def _run_live_gateway(*, handler_cls, host: str, port: int) -> None:
    server = ThreadingHTTPServer((host, port), handler_cls)
    protected = "enabled" if handler_cls.confidential_coordinator is not None else "disabled"
    print(f"ComputeMesh Unified Live Gateway listening on http://{host}:{port} (confidential={protected})")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nShutting down live gateway...")
    finally:
        server.server_close()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="ComputeMesh unified live shared-inference gateway")
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    parser.add_argument("--control-host", default=os.environ.get("COMPUTEMESH_CONTROL_HOST", "0.0.0.0"))
    parser.add_argument("--control-port", type=int, default=int(os.environ.get("COMPUTEMESH_CONTROL_PORT", "7443")))
    parser.add_argument("--control-cert", default=os.environ.get("COMPUTEMESH_CONTROL_TLS_CERT", ""))
    parser.add_argument("--control-key", default=os.environ.get("COMPUTEMESH_CONTROL_TLS_KEY", ""))
    parser.add_argument(
        "--control-module",
        default=os.environ.get("COMPUTEMESH_LIVE_CONTROL_MODULE", ""),
        help="optional module for additional site-specific live registrations",
    )
    args = parser.parse_args(argv)
    control_plane: IntegratedLiveControlPlane | None = None
    gpu_promo_dispatch: RunningGpuPromoDispatch | None = None
    confidential_runtime: LiveConfidentialRuntime | None = None
    handler_cls = None
    try:
        # Nothing customer-facing comes up before compliance, verified models and
        # durable unified-owner accounting are configured.
        assert_production_launch_gate()
        _load_models_from_env(LIVE_SHARED_RUNTIME)
        configure_live_runtime_from_module(args.control_module)
        handler_cls = build_unified_live_protected_handler()
        control_plane = _start_integrated_control_plane(
            registry=LIVE_SHARED_RUNTIME,
            host=args.control_host,
            port=args.control_port,
            cert_file=args.control_cert,
            key_file=args.control_key,
            identity_path=os.environ.get("COMPUTEMESH_IDENTITY_STATE_PATH", "").strip(),
        )
        gpu_promo_dispatch = start_optional_gpu_promo_dispatch(
            control_plane=control_plane,
            registry=LIVE_SHARED_RUNTIME,
        )
        _install_cancellable_live_gateway(handler_cls)
        # Protected mode is installed last and atomically. When explicitly enabled,
        # missing broker/signing/state/TLS/accounting inputs fail the whole startup.
        confidential_runtime = install_live_confidential_gateway(
            handler_cls=handler_cls,
            registry=LIVE_SHARED_RUNTIME,
        )
    except Exception as exc:
        if gpu_promo_dispatch is not None:
            gpu_promo_dispatch.close()
        if control_plane is not None:
            control_plane.close()
        print(f"live gateway bootstrap failed: {type(exc).__name__}: {str(exc)[:1024]}", file=sys.stderr)
        return 2
    try:
        assert handler_cls is not None
        _run_live_gateway(handler_cls=handler_cls, host=args.host, port=args.port)
    finally:
        # Confidential stores are short-lived-connection SQLite stores and require
        # no process-level close hook. Provider control is closed last so no new
        # protected admission can race shutdown.
        _ = confidential_runtime
        if gpu_promo_dispatch is not None:
            gpu_promo_dispatch.close()
        if control_plane is not None:
            control_plane.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
