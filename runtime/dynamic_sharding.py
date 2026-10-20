"""ComputeMesh Dynamic Model Sharding Engine.

Calculates layer and tensor sharding plans across heterogeneous mesh nodes based on GPU VRAM,
compute capacity (TFLOPS), network bandwidth, and model architectures.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class NodeShardCapability:
    node_id: str
    vram_bytes: int
    tflops: float = 0.0
    bandwidth_mbps: float = 1000.0
    is_local: bool = False
    healthy: bool = True


@dataclass
class ShardAssignment:
    node_id: str
    start_layer: int
    end_layer: int
    allocated_vram_bytes: int
    assigned_layers_count: int
    fraction: float
    is_local: bool


@dataclass
class ShardingPlan:
    model_id: str
    total_layers: int
    required_vram_bytes: int
    assignments: list[ShardAssignment] = field(default_factory=list)
    feasible: bool = True
    reason: str = "Success"


class DynamicShardingEngine:
    """Engine for determining optimal tensor/layer shard distribution across heterogeneous mesh nodes."""

    @staticmethod
    def calculate_sharding_plan(
        model_id: str,
        total_layers: int,
        model_vram_bytes: int,
        nodes: list[NodeShardCapability],
        *,
        reserve_vram_bytes: int = 1024 * 1024 * 1024,  # 1GB safety headroom per node
    ) -> ShardingPlan:
        healthy_nodes = [n for n in nodes if n.healthy and (n.vram_bytes - reserve_vram_bytes) > 0]
        if not healthy_nodes:
            return ShardingPlan(
                model_id=model_id,
                total_layers=total_layers,
                required_vram_bytes=model_vram_bytes,
                assignments=[],
                feasible=False,
                reason="No healthy nodes with sufficient VRAM headroom available",
            )

        total_avail_vram = sum(n.vram_bytes - reserve_vram_bytes for n in healthy_nodes)
        if total_avail_vram < model_vram_bytes:
            return ShardingPlan(
                model_id=model_id,
                total_layers=total_layers,
                required_vram_bytes=model_vram_bytes,
                assignments=[],
                feasible=False,
                reason=f"Insufficient total mesh VRAM: available {total_avail_vram / (1024**3):.2f} GB < required {model_vram_bytes / (1024**3):.2f} GB",
            )

        # Sort nodes: prioritize local node, then highest compute TFLOPS / VRAM
        sorted_nodes = sorted(
            healthy_nodes,
            key=lambda n: (1 if n.is_local else 0, n.tflops, n.vram_bytes),
            reverse=True,
        )

        # Proportional allocation based on effective VRAM capacity
        node_weights = [n.vram_bytes - reserve_vram_bytes for n in sorted_nodes]
        sum_weights = sum(node_weights)

        raw_layer_counts = [(w / sum_weights) * total_layers for w in node_weights]
        assigned_layers = [int(l) for l in raw_layer_counts]
        remaining = total_layers - sum(assigned_layers)

        # Distribute remaining layers to nodes with largest fractional remainders
        remainders = [(raw_layer_counts[i] - assigned_layers[i], i) for i in range(len(sorted_nodes))]
        remainders.sort(reverse=True, key=lambda x: x[0])
        for r in range(remaining):
            idx = remainders[r][1]
            assigned_layers[idx] += 1

        assignments: list[ShardAssignment] = []
        current_layer = 0
        vram_per_layer = model_vram_bytes / max(1, total_layers)

        for i, node in enumerate(sorted_nodes):
            layer_count = assigned_layers[i]
            if layer_count <= 0:
                continue
            start_l = current_layer
            end_l = current_layer + layer_count - 1
            current_layer += layer_count
            allocated_vram = int(layer_count * vram_per_layer)
            fraction = layer_count / max(1, total_layers)

            assignments.append(
                ShardAssignment(
                    node_id=node.node_id,
                    start_layer=start_l,
                    end_layer=end_l,
                    allocated_vram_bytes=allocated_vram,
                    assigned_layers_count=layer_count,
                    fraction=round(fraction, 4),
                    is_local=node.is_local,
                )
            )

        return ShardingPlan(
            model_id=model_id,
            total_layers=total_layers,
            required_vram_bytes=model_vram_bytes,
            assignments=assignments,
            feasible=True,
            reason="Dynamic sharding plan generated successfully",
        )
