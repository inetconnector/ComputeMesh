"""llama.cpp research integration helpers."""

from .rpc_spike import (
    RpcEndpoint,
    RpcSpikeError,
    SpikePlan,
    SpikeResult,
    build_coordinator_command,
    build_discover_command,
    build_worker_command,
    compare_results,
    completion_payload,
    run_spike,
)

__all__ = [
    "RpcEndpoint",
    "RpcSpikeError",
    "SpikePlan",
    "SpikeResult",
    "build_coordinator_command",
    "build_discover_command",
    "build_worker_command",
    "compare_results",
    "completion_payload",
    "run_spike",
]
