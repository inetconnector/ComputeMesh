"""Run unified owner accounting together with authenticated live provider control.

This is the operational entry point for server-driven GPU onboarding promo. The
provider control plane is started first so ``LIVE_SHARED_RUNTIME`` already owns the
authenticated persistent control client before the unified owner handler enables
``/v1/account/promo/gpu``.

It does not make the legacy live two-node inference path multi-node; it only combines
the owner gateway/accounting surface with the existing authenticated provider session
registry required for GPU promo verification.
"""
from __future__ import annotations

import argparse
import os
import sys
from http.server import ThreadingHTTPServer

from services.compliance.policy import assert_production_launch_gate
from services.gateway.live_server import _start_integrated_control_plane
from services.gateway.owner_server import build_unified_owner_handler
from services.gateway.server import DEFAULT_PORT
from services.orchestrator.live_control_plane import IntegratedLiveControlPlane
from services.orchestrator.live_shared_runtime import LIVE_SHARED_RUNTIME


class OwnerLiveGatewayBootstrapError(RuntimeError):
    pass


def create_owner_live_gateway_server(
    *,
    host: str,
    port: int,
    control_host: str,
    control_port: int,
    control_cert: str,
    control_key: str,
    identity_path: str,
) -> tuple[ThreadingHTTPServer, IntegratedLiveControlPlane]:
    if not identity_path:
        raise OwnerLiveGatewayBootstrapError(
            "COMPUTEMESH_IDENTITY_STATE_PATH is required for authenticated provider control"
        )
    control_plane: IntegratedLiveControlPlane | None = None
    try:
        control_plane = _start_integrated_control_plane(
            registry=LIVE_SHARED_RUNTIME,
            host=control_host,
            port=control_port,
            cert_file=control_cert,
            key_file=control_key,
            identity_path=identity_path,
        )
        handler = build_unified_owner_handler()
        server = ThreadingHTTPServer((host, port), handler)
        return server, control_plane
    except Exception:
        if control_plane is not None:
            control_plane.close()
        raise


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="ComputeMesh unified owner gateway with authenticated provider control"
    )
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    parser.add_argument(
        "--control-host",
        default=os.environ.get("COMPUTEMESH_CONTROL_HOST", "0.0.0.0"),
    )
    parser.add_argument(
        "--control-port",
        type=int,
        default=int(os.environ.get("COMPUTEMESH_CONTROL_PORT", "7443")),
    )
    parser.add_argument(
        "--control-cert",
        default=os.environ.get("COMPUTEMESH_CONTROL_TLS_CERT", ""),
    )
    parser.add_argument(
        "--control-key",
        default=os.environ.get("COMPUTEMESH_CONTROL_TLS_KEY", ""),
    )
    args = parser.parse_args(argv)

    control_plane: IntegratedLiveControlPlane | None = None
    server: ThreadingHTTPServer | None = None
    try:
        assert_production_launch_gate()
        server, control_plane = create_owner_live_gateway_server(
            host=args.host,
            port=args.port,
            control_host=args.control_host,
            control_port=args.control_port,
            control_cert=args.control_cert,
            control_key=args.control_key,
            identity_path=os.environ.get("COMPUTEMESH_IDENTITY_STATE_PATH", "").strip(),
        )
        print(
            "ComputeMesh Unified Owner + Provider Control listening: "
            f"gateway=http://{args.host}:{server.server_address[1]} "
            f"provider_control={args.control_host}:{control_plane.bound_port}"
        )
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nShutting down unified owner/live gateway...")
    finally:
        if server is not None:
            server.server_close()
        if control_plane is not None:
            control_plane.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
