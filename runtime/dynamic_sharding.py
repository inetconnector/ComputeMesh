"""ComputeMesh Dynamic Model Sharding Engine.

Calculates layer and tensor sharding plans across heterogeneous mesh nodes based on GPU VRAM,
compute capacity (TFLOPS), network bandwidth, and model architectures.
"""
from __future__ import annotations


import time
import threading
import logging
from runtime.distributed_model_cache import OffHeapCacheManager
from dataclasses import dataclass, field
from typing import Any, Sequence

log = logging.getLogger("computemesh.runtime.dynamic_sharding")

@dataclass
class PeerCapabilityHeartbeat:
    peer_id: str
    last_heartbeat: float = field(default_factory=time.time)
    vram_available: int = 0
    tflops_available: float = 0.0
    network_latency_ms: float = 0.0
    status: str = "active"


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

    failover_manager = None

    @classmethod
    def calculate_sharding_plan(
        cls,
        model_id: str,
        total_layers: int,
        model_vram_bytes: int,
        nodes: list[NodeShardCapability],
        *,
        reserve_vram_bytes: int = 1024 * 1024 * 1024,  # 1GB safety headroom per node
        enable_tensor_parallel: bool = False,
        min_bandwidth_mbps: float = 100.0,
    ) -> ShardingPlan:

        if cls.failover_manager is not None:
            import time
            now = time.time()
            with cls.failover_manager._lock:
                for n in nodes:
                    hb = cls.failover_manager._heartbeats.get(n.node_id)
                    if hb and (now - hb.last_heartbeat) > cls.failover_manager.heartbeat_timeout:
                        n.healthy = False

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


class DecentralizedShardFailover:
    """Manages zero-drop failover and atomic quota preservation for model shards."""

    def __init__(self, cache_manager: OffHeapCacheManager, heartbeat_timeout: float = 5.0):
        self.cache_manager = cache_manager
        self.heartbeat_timeout = heartbeat_timeout
        self._lock = threading.Lock()
        self._heartbeats: dict[str, PeerCapabilityHeartbeat] = {}
        self._shard_replicas: dict[str, list[str]] = {} # chunk_id -> list of peer_ids
        self._active_primary: dict[str, str] = {} # chunk_id -> primary peer_id
        self._corrupted_peers: dict[str, list[str]] = {} # chunk_id -> list of corrupted peer_ids
        self._votes: dict[str, dict[str, dict[str, str]]] = {} # chunk_id -> proposed_state -> voter_id -> status

    def register_heartbeat(self, peer_id: str, vram: int, tflops: float, latency: float) -> None:
        with self._lock:
            self._heartbeats[peer_id] = PeerCapabilityHeartbeat(
                peer_id=peer_id,
                last_heartbeat=time.time(),
                vram_available=vram,
                tflops_available=tflops,
                network_latency_ms=latency,
                status="active"
            )

    def allocate_shard_replica(self, chunk_id: str, primary_peer: str, data: bytes, replicas: list[str]) -> bool:
        """Allocates a shard in the off-heap cache and registers primary and replica peers."""
        if not self.cache_manager.allocate_chunk(chunk_id, data):
            return False

        with self._lock:
            self._active_primary[chunk_id] = primary_peer
            self._shard_replicas[chunk_id] = replicas

        return True

    def submit_vote(self, voter_id: str, chunk_id: str, proposed_state: str) -> bool:
        """Submits a vote for a proposed state (e.g., promotion, eviction) for a chunk. Returns True if a 2/3 Byzantine-tolerant quorum is reached."""
        with self._lock:
            if voter_id not in self._heartbeats or self._heartbeats[voter_id].status != "active":
                return False

            if chunk_id not in self._votes:
                self._votes[chunk_id] = {}
            if proposed_state not in self._votes[chunk_id]:
                self._votes[chunk_id][proposed_state] = {}

            self._votes[chunk_id][proposed_state][voter_id] = "voted"

            now = time.time()
            active_peers_count = sum(
                1 for hb in self._heartbeats.values()
                if (now - hb.last_heartbeat) <= self.heartbeat_timeout and hb.status == "active"
            )

            # Byzantine tolerance requires > 2/3 majority
            votes_received = len(self._votes[chunk_id][proposed_state])
            quorum_needed = (2 * active_peers_count // 3) + 1

            if votes_received >= quorum_needed:
                log.info("Byzantine quorum reached for chunk %s state %s (%d/%d active peers)", chunk_id, proposed_state, votes_received, active_peers_count)
                # Clear votes after consensus to allow future votes
                self._votes[chunk_id] = {}
                return True
            return False

    def report_corrupted_replica(self, chunk_id: str, peer_id: str) -> None:
        """Reports a corrupted replica (e.g., failed Merkle verification) to exclude it from being primary."""
        with self._lock:
            if chunk_id not in self._corrupted_peers:
                self._corrupted_peers[chunk_id] = []
            if peer_id not in self._corrupted_peers[chunk_id]:
                self._corrupted_peers[chunk_id].append(peer_id)
                log.warning("Peer %s reported as corrupted for chunk %s", peer_id, chunk_id)

    def check_failover(self, chunk_id: str) -> str | None:
        """Checks if the primary peer is dead or corrupted and performs failover if necessary. Returns the new primary peer or None if failed."""
        with self._lock:
            if chunk_id not in self._active_primary:
                return None

            primary_peer = self._active_primary[chunk_id]
            primary_hb = self._heartbeats.get(primary_peer)
            now = time.time()

            corrupted_for_chunk = self._corrupted_peers.get(chunk_id, [])

            # Check if primary is alive and NOT corrupted
            if primary_hb and (now - primary_hb.last_heartbeat) <= self.heartbeat_timeout and primary_hb.status == "active" and primary_peer not in corrupted_for_chunk:
                return primary_peer # Primary is still alive and healthy

            # Primary is dead or corrupted, perform failover
            reason = "corrupted" if primary_peer in corrupted_for_chunk else "timed out"
            log.warning("Primary peer %s for chunk %s %s. Initiating failover.", primary_peer, chunk_id, reason)
            if primary_hb and reason == "timed out":
                primary_hb.status = "dead"

            replicas = self._shard_replicas.get(chunk_id, [])
            alive_replicas = []
            for replica in replicas:
                if replica in corrupted_for_chunk:
                    continue # Skip corrupted replicas
                hb = self._heartbeats.get(replica)
                if hb and (now - hb.last_heartbeat) <= self.heartbeat_timeout and hb.status == "active":
                    alive_replicas.append((replica, hb))

            if not alive_replicas:
                log.error("All valid replicas for chunk %s have dropped out or corrupted. Freeing atomic quota.", chunk_id)
                # No valid replicas alive, free the chunk to preserve quota
                self._active_primary.pop(chunk_id, None)
                self._shard_replicas.pop(chunk_id, None)
                pass
            else:
                # Select the best replica (e.g., lowest latency or highest VRAM)
                alive_replicas.sort(key=lambda x: x[1].network_latency_ms)
                new_primary = alive_replicas[0][0]
                self._active_primary[chunk_id] = new_primary
                log.info("Successfully failed over chunk %s to new primary %s.", chunk_id, new_primary)
                return new_primary

        # Free chunk if all replicas drop
        if not alive_replicas:
            self.cache_manager.free_chunk(chunk_id)
            return None
