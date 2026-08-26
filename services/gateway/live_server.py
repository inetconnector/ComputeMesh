"""Run the normal ComputeMesh gateway with live shared-runtime dependencies.

A deployment control-plane module must register current authenticated NodeSessions,
profiles/benchmarks, network measurements, models and its live NodeControlClient in
`LIVE_SHARED_RUNTIME` before the HTTP listener starts.
"""
from __future__ import annotations

import argparse
import importlib
import os
import sys
from typing import Callable

from services.gateway.live_bootstrap import install_live_shared_gateway
from services.gateway.server import DEFAULT_PORT, run_gateway_server
from services.orchestrator.live_shared_runtime import LIVE_SHARED_RUNTIME, LiveSharedRuntimeRegistry


class LiveGatewayBootstrapError(RuntimeError):
    pass


def configure_live_runtime_from_module(
    module_name: str,
    *,
    registry: LiveSharedRuntimeRegistry = LIVE_SHARED_RUNTIME,
) -> None:
    if not module_name or len(module_name) > 256:
        raise LiveGatewayBootstrapError("a bounded control-plane module name is required")
    module = importlib.import_module(module_name)
    configure: Callable[[LiveSharedRuntimeRegistry], None] | None = getattr(
        module, "configure_computemesh_live_runtime", None
    )
    if configure is None or not callable(configure):
        raise LiveGatewayBootstrapError(
            "control-plane module must export configure_computemesh_live_runtime(registry)"
        )
    configure(registry)
    # Force the two critical live dependencies to exist at startup. Placement itself
    # remains request-time because profiles/network state can change continuously.
    registry.control_client


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="ComputeMesh live shared-inference gateway")
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    parser.add_argument(
        "--control-module",
        default=os.environ.get("COMPUTEMESH_LIVE_CONTROL_MODULE", ""),
        help="Python module that registers live NodeSessions/scheduler inputs/control client",
    )
    args = parser.parse_args(argv)
    try:
        configure_live_runtime_from_module(args.control_module)
        install_live_shared_gateway()
    except Exception as exc:
        print(f"live gateway bootstrap failed: {type(exc).__name__}: {str(exc)[:1024]}", file=sys.stderr)
        return 2
    run_gateway_server(host=args.host, port=args.port)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
