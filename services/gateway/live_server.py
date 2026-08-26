"""Run the ComputeMesh gateway with automatic persistent provider registration.

Providers authenticate over the persistent control channel and push their current
profile/runtime/benchmarks into LIVE_SHARED_RUNTIME. Models are loaded from a local
content-addressed catalog whose GGUF files are verified against the standard
ComputeMesh model manifests before serving starts.
"""
from __future__ import annotations

import argparse
import importlib
import os
from pathlib import Path
import sys
from typing import Callable

from protocol.node_identity import Ed25519ChallengeVerifier
from services.gateway.live_bootstrap import install_live_shared_gateway
from services.gateway.server import DEFAULT_PORT, run_gateway_server
from services.identity.store import SQLiteIdentityStore
from services.orchestrator.live_control_plane import IntegratedLiveControlPlane
from services.orchestrator.live_model_catalog import register_verified_live_models
from services.orchestrator.live_shared_runtime import LIVE_SHARED_RUNTIME, LiveSharedRuntimeRegistry


class LiveGatewayBootstrapError(RuntimeError):
    pass


def configure_live_runtime_from_module(
    module_name: str,
    *,
    registry: LiveSharedRuntimeRegistry = LIVE_SHARED_RUNTIME,
) -> None:
    """Optionally load additional site-specific live state."""
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
        verifier=Ed25519ChallengeVerifier(SQLiteIdentityStore(identity_path)),
        host=host,
        port=port,
        cert_file=cert_file,
        key_file=key_file,
    )
    plane.start()
    return plane


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="ComputeMesh live shared-inference gateway")
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
    try:
        _load_models_from_env(LIVE_SHARED_RUNTIME)
        configure_live_runtime_from_module(args.control_module)
        control_plane = _start_integrated_control_plane(
            registry=LIVE_SHARED_RUNTIME,
            host=args.control_host,
            port=args.control_port,
            cert_file=args.control_cert,
            key_file=args.control_key,
            identity_path=os.environ.get("COMPUTEMESH_IDENTITY_STATE_PATH", "").strip(),
        )
        install_live_shared_gateway()
    except Exception as exc:
        if control_plane is not None:
            control_plane.close()
        print(f"live gateway bootstrap failed: {type(exc).__name__}: {str(exc)[:1024]}", file=sys.stderr)
        return 2
    try:
        run_gateway_server(host=args.host, port=args.port)
    finally:
        if control_plane is not None:
            control_plane.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
