"""ComputeMesh Dynamic Model Sharding Engine.

Calculates layer and tensor sharding plans across heterogeneous mesh nodes based on GPU VRAM,
compute capacity (TFLOPS), network bandwidth, and model architectures.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Sequence


@dataclass
class NodeShardCapability:
    node_id: str
    vram_bytes: int
    tflops: float = 0.0
    bandwidth_mbps: float = 1000.0
    is_local: bool = False
    healthy: bool = True
    tensor_parallel_supported: bool = True


@dataclass
class ShardAssignment:
    node_id: str
    start_layer: int
    end_layer: int
    allocated_vram_bytes: int
    assigned_layers_count: int
    fraction: float
    is_local: bool
    tensor_parallel_degree: int = 1
    estimated_transfer_ms: float = 0.0


@dataclass
class ShardingPlan:
    model_id: str
    total_layers: int
    required_vram_bytes: int
    assignments: list[ShardAssignment] = field(default_factory=list)
    feasible: bool = True
    reason: str = "Success"
    estimated_pipeline_latency_ms: float = 0.0
    tensor_parallel_enabled: bool = False


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
        enable_tensor_parallel: bool = False,
        min_bandwidth_mbps: float = 100.0,
    ) -> ShardingPlan:
        healthy_nodes = [
            n for n in nodes
            if n.healthy and (n.vram_bytes - reserve_vram_bytes) > 0 and n.bandwidth_mbps >= min_bandwidth_mbps
        ]
        if not healthy_nodes:
            return ShardingPlan(
                model_id=model_id,
                total_layers=total_layers,
                required_vram_bytes=model_vram_bytes,
                assignments=[],
                feasible=False,
                reason="No healthy nodes with sufficient VRAM headroom available",
                tensor_parallel_enabled=enable_tensor_parallel,
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
                tensor_parallel_enabled=enable_tensor_parallel,
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
        total_transfer_ms = 0.0

        for i, node in enumerate(sorted_nodes):
            layer_count = assigned_layers[i]
            if layer_count <= 0:
                continue
            start_l = current_layer
            end_l = current_layer + layer_count - 1
            current_layer += layer_count
            allocated_vram = int(layer_count * vram_per_layer)
            fraction = layer_count / max(1, total_layers)

            tp_degree = 1
            if enable_tensor_parallel and node.tensor_parallel_supported and len(sorted_nodes) > 1:
                tp_degree = min(2, len(sorted_nodes))

            # Estimate activation transfer latency per layer over network
            activation_bytes_per_layer = (4096 * 2) * 2  # hidden_dim 4096 float16 estimate
            bw_bps = max(1.0, node.bandwidth_mbps) * 1e6 / 8.0
            transfer_ms = (activation_bytes_per_layer / bw_bps) * 1000.0 if not node.is_local else 0.1
            total_transfer_ms += transfer_ms * layer_count

            assignments.append(
                ShardAssignment(
                    node_id=node.node_id,
                    start_layer=start_l,
                    end_layer=end_l,
                    allocated_vram_bytes=allocated_vram,
                    assigned_layers_count=layer_count,
                    fraction=round(fraction, 4),
                    is_local=node.is_local,
                    tensor_parallel_degree=tp_degree,
                    estimated_transfer_ms=round(transfer_ms, 3),
                )
            )

        # Estimate compute pipeline latency based on tflops and layer allocation
        avg_tflops = sum(n.tflops for n in sorted_nodes) / max(1, len(sorted_nodes))
        compute_time_ms = (model_vram_bytes / (1024**3)) * (100.0 / max(1.0, avg_tflops))
        est_pipeline_latency = round(compute_time_ms + total_transfer_ms, 2)

        return ShardingPlan(
            model_id=model_id,
            total_layers=total_layers,
            required_vram_bytes=model_vram_bytes,
            assignments=assignments,
            feasible=True,
            reason="Dynamic sharding plan generated successfully",
            estimated_pipeline_latency_ms=est_pipeline_latency,
            tensor_parallel_enabled=enable_tensor_parallel,
        )
