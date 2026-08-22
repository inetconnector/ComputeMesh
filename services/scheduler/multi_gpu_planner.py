#!/usr/bin/env python3
"""ComputeMesh Multi-GPU Mining Rig & Heterogeneous Placement Engine.

Calculates exact layer partition splits, KV-cache memory budgets, and RPC tensor
mappings for multi-GPU provider rigs (e.g. 5x 8GB AMD/NVIDIA rigs) and heterogeneous
mixed-capacity GPU clusters.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
import json
import math
from pathlib import Path
from typing import Any


class MultiGpuPlanningError(ValueError):
    """Raised when a model cannot be partitioned across the available GPUs."""


@dataclass(frozen=True)
class GpuDeviceSpec:
    device_id: int
    name: str
    vendor: str  # 'nvidia', 'amd', 'intel', 'apple'
    vram_bytes: int
    pci_bus: str = ""


@dataclass(frozen=True)
class GpuLayerAllocation:
    device_id: int
    name: str
    vendor: str
    layer_start: int
    layer_end: int
    layers_assigned: int
    vram_used_bytes: int
    vram_total_bytes: int
    utilization_percent: float


@dataclass(frozen=True)
class MultiGpuPlan:
    model_id: str
    total_layers: int
    model_weight_bytes: int
    total_rig_vram_bytes: int
    allocations: tuple[GpuLayerAllocation, ...]
    tensor_split_ratios: list[float]
    is_feasible: bool
    status_reason: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "model_id": self.model_id,
            "total_layers": self.total_layers,
            "model_weight_bytes": self.model_weight_bytes,
            "total_rig_vram_bytes": self.total_rig_vram_bytes,
            "is_feasible": self.is_feasible,
            "status_reason": self.status_reason,
            "tensor_split_ratios": self.tensor_split_ratios,
            "allocations": [asdict(a) for a in self.allocations],
        }


def plan_multi_gpu_rig(
    *,
    model_id: str,
    total_layers: int,
    model_weight_bytes: int,
    devices: list[GpuDeviceSpec],
    usable_memory_fraction: float = 0.90,
    kv_cache_overhead_bytes_per_layer: int = 16 * 1024 * 1024,  # 16 MB per layer KV cache (context 4K)
) -> MultiGpuPlan:
    """Partitions model layers across multi-GPU rigs proportionally to VRAM capacity."""
    if not devices:
        raise MultiGpuPlanningError("At least one GPU device is required for multi-GPU planning.")
    if total_layers <= 0:
        raise MultiGpuPlanningError(f"Invalid total_layers: {total_layers}")
    if model_weight_bytes <= 0:
        raise MultiGpuPlanningError(f"Invalid model_weight_bytes: {model_weight_bytes}")

    total_rig_vram = sum(d.vram_bytes for d in devices)
    total_usable_vram = int(total_rig_vram * usable_memory_fraction)

    # Base weight per layer
    weight_per_layer = model_weight_bytes // total_layers
    total_model_footprint = model_weight_bytes + (kv_cache_overhead_bytes_per_layer * total_layers)

    if total_model_footprint > total_usable_vram:
        return MultiGpuPlan(
            model_id=model_id,
            total_layers=total_layers,
            model_weight_bytes=model_weight_bytes,
            total_rig_vram_bytes=total_rig_vram,
            allocations=(),
            tensor_split_ratios=[],
            is_feasible=False,
            status_reason=f"Insufficient total rig VRAM: required {total_model_footprint / (1024**3):.2f} GB, usable {total_usable_vram / (1024**3):.2f} GB",
        )

    # Calculate proportional layer counts
    allocations_list: list[GpuLayerAllocation] = []
    tensor_splits: list[float] = []

    assigned_layers = 0
    current_layer_idx = 0

    for i, dev in enumerate(devices):
        dev_usable_vram = int(dev.vram_bytes * usable_memory_fraction)
        split_ratio = dev.vram_bytes / total_rig_vram
        tensor_splits.append(round(split_ratio, 4))

        if i == len(devices) - 1:
            # Assign remainder to the last device
            layer_count = total_layers - assigned_layers
        else:
            layer_count = int(math.floor(total_layers * (dev.vram_bytes / total_rig_vram)))
            # Ensure at least 1 layer if device has capacity and layers remain
            if layer_count == 0 and (total_layers - assigned_layers) > (len(devices) - i):
                layer_count = 1

        assigned_layers += layer_count
        layer_start = current_layer_idx
        layer_end = current_layer_idx + layer_count
        current_layer_idx = layer_end

        dev_mem_used = (layer_count * weight_per_layer) + (layer_count * kv_cache_overhead_bytes_per_layer)
        utilization = round((dev_mem_used / dev.vram_bytes) * 100, 2) if dev.vram_bytes > 0 else 0.0

        allocations_list.append(
            GpuLayerAllocation(
                device_id=dev.device_id,
                name=dev.name,
                vendor=dev.vendor,
                layer_start=layer_start,
                layer_end=layer_end,
                layers_assigned=layer_count,
                vram_used_bytes=dev_mem_used,
                vram_total_bytes=dev.vram_bytes,
                utilization_percent=utilization,
            )
        )

    return MultiGpuPlan(
        model_id=model_id,
        total_layers=total_layers,
        model_weight_bytes=model_weight_bytes,
        total_rig_vram_bytes=total_rig_vram,
        allocations=tuple(allocations_list),
        tensor_split_ratios=tensor_splits,
        is_feasible=True,
        status_reason="Optimal proportional layer sharding calculated successfully",
    )
