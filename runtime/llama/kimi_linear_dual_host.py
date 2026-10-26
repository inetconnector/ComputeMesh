"""Opt-in Kimi-Linear GGUF execution on one CUDA coordinator and six RPC GPUs.

The RPC transport is upstream experimental plaintext.  Only a loopback
endpoint delivered through an independently authenticated tunnel is accepted.
No tunnel, remote daemon, model or credential is provisioned by this program.
The existing ComputeMesh RPC spike executes actual llama-server work.
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

from runtime.llama.rpc_spike import (
    RpcEndpoint,
    RpcSpikeError,
    SpikePlan,
    build_coordinator_command,
    parse_runtime_build_identity,
    run_spike,
    runtime_version,
    sha256_file,
)
from runtime.llama.shared_trial import discover_devices

_MODEL_NAMES = {
    "Q4_K_M": ("Kimi-Linear-48B-A3B-Instruct-Q4_K_M.gguf", 27_000_000_000, 33_000_000_000),
    "Q6_K": ("Kimi-Linear-48B-A3B-Instruct-Q6_K.gguf", 38_000_000_000, 43_000_000_000),
}
_FREE_MIB_RE = re.compile(r"\b(\d+)\s+MiB\s+free\b", re.IGNORECASE)
_SHA_RE = re.compile(r"[0-9a-fA-F]{64}")
_COMMIT_RE = re.compile(r"[0-9a-fA-F]{7,40}")


class KimiDualHostError(RuntimeError):
    """One of the required real model/accelerator/RPC preconditions failed."""


@dataclass(frozen=True)
class KimiDualHostPlan:
    spike: SpikePlan
    sha256: str
    runtime_commit: str
    devices: tuple[str, ...]
    usable_mib: tuple[int, ...]

    def receipt(self) -> dict[str, object]:
        return {
            "schema_version": 1,
            "status": "PREFLIGHT_ONLY",
            "model_basename": self.spike.model.name,
            "model_sha256": self.sha256,
            "model_bytes": self.spike.model.stat().st_size,
            "runtime_commit": self.runtime_commit,
            "rpc_endpoint": self.spike.rpc_endpoints[0].text(),
            "devices": list(self.devices),
            "usable_mib_by_device": list(self.usable_mib),
            "tensor_split": list(self.spike.tensor_split),
            "context_size": self.spike.context_size,
            "command": build_coordinator_command(self.spike),
            "limitations": "No inference, GPU ownership, encrypted tunnel or peer identity is proven by this preflight.",
        }


def _usable_mib(description: str, reserve_mib: int) -> int:
    matches = _FREE_MIB_RE.findall(description)
    if len(matches) != 1:
        raise KimiDualHostError("GPU memory telemetry is missing or ambiguous; refusing guessed placement")
    result = int(matches[0]) - reserve_mib
    if result <= 0:
        raise KimiDualHostError("GPU lacks the mandatory VRAM reserve")
    return result


def build_kimi_dual_host_plan(
    *,
    llama_server: Path,
    model: Path,
    model_sha256: str,
    quant: str,
    worker_rpc: RpcEndpoint,
    expected_runtime_commit: str,
    coordinator_device: str = "CUDA0",
    expected_rpc_gpus: int = 6,
    reserve_mib: int = 1024,
    total_headroom_mib: int = 2048,
    context_size: int = 2048,
    port: int = 18080,
) -> KimiDualHostPlan:
    """Discover actual devices and return an executable, fail-closed RPC plan.

    This is a research/physical-acceptance entry point, not an authorization to
    expose insecure ggml RPC to an untrusted LAN or the public Internet.
    """
    if worker_rpc.host != "127.0.0.1":
        raise KimiDualHostError("insecure upstream RPC requires a separately authenticated loopback tunnel")
    if quant not in _MODEL_NAMES:
        raise KimiDualHostError("only Kimi-Linear Q4_K_M and Q6_K are approved for this trial")
    if not _SHA_RE.fullmatch(model_sha256):
        raise KimiDualHostError("a full trusted model SHA-256 is required")
    if not _COMMIT_RE.fullmatch(expected_runtime_commit):
        raise KimiDualHostError("a pinned llama.cpp runtime commit is required")
    if expected_rpc_gpus != 6:
        raise KimiDualHostError("the initial AMD Polaris trial requires exactly six RPC GPUs")
    if not 256 <= reserve_mib <= 4096 or not 512 <= total_headroom_mib <= 8192:
        raise KimiDualHostError("VRAM reserve/headroom is out of bounds")
    if not 128 <= context_size <= 8192:
        raise KimiDualHostError("the initial Kimi trial context must be 128..8192")
    if not 1 <= port <= 65535:
        raise KimiDualHostError("invalid loopback inference port")
    if model.is_symlink() or not model.is_file():
        raise KimiDualHostError("model must be a regular local GGUF file")
    expected_name, minimum, maximum = _MODEL_NAMES[quant]
    # GGUF providers can prefix filenames, but quant and architecture must be exact.
    if not model.name.endswith(expected_name):
        raise KimiDualHostError("model filename does not match the selected Kimi-Linear GGUF quant")
    size = model.stat().st_size
    if size < minimum or size > maximum:
        raise KimiDualHostError("model size is incompatible with the selected Kimi quantization")
    with model.open("rb") as stream:
        if stream.read(4) != b"GGUF":
            raise KimiDualHostError("model is not a GGUF artifact")
    actual_hash = sha256_file(model)
    if actual_hash.lower() != model_sha256.lower():
        raise KimiDualHostError("GGUF SHA-256 does not match the trusted model manifest")
    if llama_server.is_symlink() or not llama_server.is_file():
        raise KimiDualHostError("llama-server must be an existing regular executable")
    identity = parse_runtime_build_identity(runtime_version(llama_server))
    expected_commit = expected_runtime_commit.lower()
    if not (identity.commit.startswith(expected_commit) or expected_commit.startswith(identity.commit)):
        raise KimiDualHostError("local llama-server commit does not match the pinned trial runtime")

    devices = discover_devices(llama_server, (worker_rpc,))
    local = [device for device in devices if device.name == coordinator_device and device.name.startswith("CUDA")]
    remote = sorted((device for device in devices if device.name.startswith("RPC")), key=lambda item: item.name)
    if len(local) != 1 or len(remote) != expected_rpc_gpus or len({d.name for d in remote}) != expected_rpc_gpus:
        raise KimiDualHostError("device discovery did not prove one selected CUDA GPU and six distinct RPC devices")
    ordered = (local[0], *remote)
    split_mib = tuple(_usable_mib(device.description, reserve_mib) for device in ordered)
    available_bytes = (sum(split_mib) - total_headroom_mib) * 1024 * 1024
    if size > available_bytes:
        raise KimiDualHostError("verified model size exceeds current combined GPU memory budget")
    spike = SpikePlan(
        llama_server=llama_server,
        model=model,
        rpc_endpoints=(worker_rpc,),
        devices=tuple(device.name for device in ordered),
        tensor_split=tuple(float(value) for value in split_mib),
        mode="shared_rpc",
        local_port=port,
        context_size=context_size,
        n_predict=32,
        seed=1,
    )
    return KimiDualHostPlan(spike, actual_hash, identity.commit, spike.devices, split_mib)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Fail-closed Kimi-Linear 48B dual-host RPC trial")
    parser.add_argument("command", choices=("probe", "run", "serve"))
    parser.add_argument("--llama-server", required=True, type=Path)
    parser.add_argument("--model", required=True, type=Path)
    parser.add_argument("--model-sha256", required=True)
    parser.add_argument("--quant", required=True, choices=tuple(_MODEL_NAMES))
    parser.add_argument("--worker-rpc", required=True, type=RpcEndpoint.parse)
    parser.add_argument("--runtime-commit", required=True)
    parser.add_argument("--coordinator-device", default="CUDA0")
    parser.add_argument("--reserve-mib", type=int, default=1024)
    parser.add_argument("--headroom-mib", type=int, default=2048)
    parser.add_argument("--context-size", type=int, default=2048)
    parser.add_argument("--port", type=int, default=18080)
    parser.add_argument("--output-dir", type=Path)
    args = parser.parse_args(argv)
    try:
        plan = build_kimi_dual_host_plan(
            llama_server=args.llama_server, model=args.model,
            model_sha256=args.model_sha256, quant=args.quant,
            worker_rpc=args.worker_rpc, expected_runtime_commit=args.runtime_commit,
            coordinator_device=args.coordinator_device,
            reserve_mib=args.reserve_mib, total_headroom_mib=args.headroom_mib,
            context_size=args.context_size, port=args.port,
        )
        if args.command == "probe":
            print(json.dumps(plan.receipt(), sort_keys=True, indent=2))
            return 0
        if args.command == "run":
            if args.output_dir is None:
                raise KimiDualHostError("run requires --output-dir for the bounded actual-inference receipt")
            result = run_spike(
                plan.spike,
                prompt="ComputeMesh Kimi-Linear distributed inference acceptance. Answer READY.",
                output_dir=args.output_dir,
            )
            print(str(result))
            return 0
        # Persistent loopback inference, suitable for the existing provider-agent
        # HTTP backend once it has been separately authenticated and enrolled.
        return subprocess.run(build_coordinator_command(plan.spike), check=False).returncode
    except (ValueError, OSError, RpcSpikeError, KimiDualHostError) as exc:
        print(f"Kimi dual-host trial refused: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
