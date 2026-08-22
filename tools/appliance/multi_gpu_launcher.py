#!/usr/bin/env python3
"""ComputeMesh Multi-GPU Inference Launcher & Layer Allocator.

Calculates optimal tensor split / layer allocation across heterogeneous multi-GPU
mining rigs (e.g. 5x 8GB cards = 40GB total VRAM) and produces executable startup
arguments for local llama.cpp multi-GPU or distributed RPC worker daemons.
"""
from __future__ import annotations

import argparse
from dataclasses import dataclass
import json
from pathlib import Path
import sys
from typing import Any, Sequence

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from tools.appliance.hardware_detector import GpuDevice, RigInventory, scan_rig_hardware


@dataclass(frozen=True)
class GpuAllocation:
    gpu_index: int
    pci_slot: str
    model_name: str
    vram_bytes: int
    tensor_split_fraction: float
    allocated_layers: int
    driver_backend: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "gpu_index": self.gpu_index,
            "pci_slot": self.pci_slot,
            "model_name": self.model_name,
            "vram_bytes": self.vram_bytes,
            "tensor_split_fraction": round(self.tensor_split_fraction, 4),
            "allocated_layers": self.allocated_layers,
            "driver_backend": self.driver_backend,
        }


@dataclass(frozen=True)
class MultiGpuPlan:
    total_gpus: int
    total_vram_bytes: int
    total_model_layers: int
    allocations: list[GpuAllocation]
    tensor_split_arg: str
    devices_arg: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "total_gpus": self.total_gpus,
            "total_vram_bytes": self.total_vram_bytes,
            "total_model_layers": self.total_model_layers,
            "allocations": [a.to_dict() for a in self.allocations],
            "tensor_split_arg": self.tensor_split_arg,
            "devices_arg": self.devices_arg,
        }


def compute_multi_gpu_allocation(
    inventory: RigInventory,
    total_model_layers: int = 24,
) -> MultiGpuPlan:
    """Compute proportional VRAM split and layer allocation across all healthy GPUs."""
    healthy_gpus = [g for g in inventory.gpus if g.healthy and g.vram_bytes > 0]
    if not healthy_gpus:
        raise ValueError("No healthy GPUs with VRAM detected on the rig.")

    total_vram = sum(g.vram_bytes for g in healthy_gpus)
    allocations: list[GpuAllocation] = []
    
    fractions: list[float] = [g.vram_bytes / total_vram for g in healthy_gpus]
    split_str = ",".join(f"{f:.3f}" for f in fractions)
    
    # Proportional layer assignment
    layers_remaining = total_model_layers
    device_names: list[str] = []
    
    for idx, (gpu, frac) in enumerate(zip(healthy_gpus, fractions)):
        if idx == len(healthy_gpus) - 1:
            assigned = layers_remaining
        else:
            assigned = int(round(frac * total_model_layers))
            assigned = min(assigned, layers_remaining)
            layers_remaining -= assigned
        
        backend_prefix = "CUDA" if gpu.driver_backend == "cuda" else "Vulkan"
        device_names.append(f"{backend_prefix}{gpu.index}")
        
        allocations.append(
            GpuAllocation(
                gpu_index=gpu.index,
                pci_slot=gpu.pci_slot,
                model_name=gpu.model_name,
                vram_bytes=gpu.vram_bytes,
                tensor_split_fraction=frac,
                allocated_layers=assigned,
                driver_backend=gpu.driver_backend,
            )
        )

    return MultiGpuPlan(
        total_gpus=len(healthy_gpus),
        total_vram_bytes=total_vram,
        total_model_layers=total_model_layers,
        allocations=allocations,
        tensor_split_arg=split_str,
        devices_arg=",".join(device_names),
    )


def build_llama_server_command(
    executable: str,
    model_path: str,
    plan: MultiGpuPlan,
    host: str = "0.0.0.0",
    port: int = 8080,
    context_size: int = 4096,
    extra_args: Sequence[str] = (),
) -> list[str]:
    """Generate commandline to launch llama-server utilizing all miner GPUs."""
    cmd = [
        executable,
        "-m", model_path,
        "--host", host,
        "--port", str(port),
        "-c", str(context_size),
        "-ngl", str(plan.total_model_layers),
        "-ts", plan.tensor_split_arg,
        "--devices", plan.devices_arg,
        *extra_args,
    ]
    return cmd


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="ComputeMesh Multi-GPU Inference Launcher")
    parser.add_argument("--model-layers", type=int, default=24, help="Total layer count of the model (e.g. 24 for 0.5B/3B, 32 for 7B/8B)")
    parser.add_argument("--inventory-file", type=Path, help="Optional path to pre-scanned inventory JSON")
    args = parser.parse_args(argv)

    if args.inventory_file and args.inventory_file.exists():
        raw = json.loads(args.inventory_file.read_text(encoding="utf-8"))
        gpus = [
            GpuDevice(
                index=g["index"],
                pci_slot=g["pci_slot"],
                vendor=g["vendor"],
                model_name=g["model_name"],
                vram_bytes=g["vram_bytes"],
                pcie_gen=g.get("pcie_gen"),
                pcie_width=g.get("pcie_width"),
                driver_backend=g["driver_backend"],
                is_headless=g.get("is_headless", False),
                healthy=g.get("healthy", True),
            )
            for g in raw["gpus"]
        ]
        inventory = RigInventory(
            schema_version=raw["schema_version"],
            captured_at=raw["captured_at"],
            host_architecture=raw["host_architecture"],
            total_gpus=len(gpus),
            total_vram_bytes=sum(g.vram_bytes for g in gpus),
            gpus=gpus,
            pcie_riser_warning=raw.get("pcie_riser_warning", False),
        )
    else:
        inventory = scan_rig_hardware()

    try:
        plan = compute_multi_gpu_allocation(inventory, total_model_layers=args.model_layers)
        print(json.dumps(plan.to_dict(), indent=2, sort_keys=True))
        return 0
    except Exception as exc:
        print(f"Error computing allocation: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
