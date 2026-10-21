"""ComputeMesh Multi-Cluster Federation Engine.

Enables resilient cross-cluster capacity aggregation, health monitoring,
and topology-aware inference placement across distributed mesh clusters.
"""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

log = logging.getLogger("computemesh.runtime.multi_cluster_federation")


@dataclass
class ClusterNode:
    """Represents an individual compute node within a federated cluster."""
    node_id: str
    cluster_id: str
    vram_bytes: int
    tflops: float
    region: str = "us-east"
    ping_ms: float = 12.0
    is_active: bool = True
    health_score: float = 1.0


@dataclass
class FederatedCluster:
    """Represents a federated compute cluster containing multiple nodes."""
    cluster_id: str
    name: str
    region: str
    nodes: Dict[str, ClusterNode] = field(default_factory=dict)
    last_sync_timestamp: float = field(default_factory=time.time)

    @property
    def total_vram_bytes(self) -> int:
        return sum(n.vram_bytes for n in self.nodes.values() if n.is_active)

    @property
    def total_tflops(self) -> float:
        return sum(n.tflops for n in self.nodes.values() if n.is_active)

    @property
    def active_nodes_count(self) -> int:
        return sum(1 for n in self.nodes.values() if n.is_active)


class MultiClusterFederator:
    """Production Multi-Cluster Federation engine managing cross-cluster placement and state."""

    def __init__(self) -> None:
        self._clusters: Dict[str, FederatedCluster] = {}
        # Pre-seed default primary cluster
        self.register_cluster(
            cluster_id="cluster-primary",
            name="Primary Compute Cluster",
            region="eu-central",
            nodes=[
                ClusterNode(
                    node_id="local-node-01",
                    cluster_id="cluster-primary",
                    vram_bytes=24 * 1024 * 1024 * 1024,
                    tflops=48.6,
                    region="eu-central",
                    is_active=True,
                )
            ],
        )

    def register_cluster(
        self,
        cluster_id: str,
        name: str,
        region: str,
        nodes: Optional[List[ClusterNode]] = None,
    ) -> FederatedCluster:
        """Registers or updates a federated compute cluster."""
        if cluster_id not in self._clusters:
            self._clusters[cluster_id] = FederatedCluster(
                cluster_id=cluster_id,
                name=name,
                region=region,
                nodes={},
            )
        cluster = self._clusters[cluster_id]
        cluster.name = name
        cluster.region = region
        cluster.last_sync_timestamp = time.time()

        if nodes:
            for node in nodes:
                node.cluster_id = cluster_id
                cluster.nodes[node.node_id] = node

        log.info(f"Registered federated cluster {cluster_id} ({name}) with {len(cluster.nodes)} nodes")
        return cluster

    def update_node_health(
        self, cluster_id: str, node_id: str, ping_ms: float, is_active: bool = True
    ) -> bool:
        """Updates health status for a specific node in a federated cluster."""
        if cluster_id not in self._clusters:
            return False
        cluster = self._clusters[cluster_id]
        if node_id not in cluster.nodes:
            return False

        node = cluster.nodes[node_id]
        node.ping_ms = max(0.1, ping_ms)
        node.is_active = is_active
        # Dynamic health score calculation
        if not is_active:
            node.health_score = 0.0
        else:
            node.health_score = max(0.1, min(1.0, 100.0 / max(1.0, ping_ms)))

        cluster.last_sync_timestamp = time.time()
        return True

    def sync_cluster_states(self, payload_list: List[Dict[str, Any]]) -> int:
        """Synchronizes remote cluster states from federation heartbeat payload."""
        synced_count = 0
        for payload in payload_list:
            cid = str(payload.get("cluster_id", ""))
            name = str(payload.get("name", f"Cluster {cid}"))
            region = str(payload.get("region", "global"))
            nodes_data = payload.get("nodes", [])

            nodes_list = []
            for nd in nodes_data:
                nodes_list.append(
                    ClusterNode(
                        node_id=str(nd.get("node_id", "")),
                        cluster_id=cid,
                        vram_bytes=int(nd.get("vram_bytes", 0)),
                        tflops=float(nd.get("tflops", 0.0)),
                        region=str(nd.get("region", region)),
                        ping_ms=float(nd.get("ping_ms", 10.0)),
                        is_active=bool(nd.get("is_active", True)),
                    )
                )

            self.register_cluster(cluster_id=cid, name=name, region=region, nodes=nodes_list)
            synced_count += 1

        return synced_count

    def get_federated_capacity(self) -> Dict[str, Any]:
        """Returns total aggregated capacity across all federated clusters."""
        total_clusters = len(self._clusters)
        total_active_nodes = sum(c.active_nodes_count for c in self._clusters.values())
        total_vram_bytes = sum(c.total_vram_bytes for c in self._clusters.values())
        total_tflops = sum(c.total_tflops for c in self._clusters.values())

        clusters_summary = []
        for c in self._clusters.values():
            clusters_summary.append(
                {
                    "cluster_id": c.cluster_id,
                    "name": c.name,
                    "region": c.region,
                    "active_nodes": c.active_nodes_count,
                    "vram_gb": round(c.total_vram_bytes / (1024**3), 2),
                    "tflops": round(c.total_tflops, 2),
                    "last_sync_timestamp": c.last_sync_timestamp,
                }
            )

        return {
            "total_clusters": total_clusters,
            "total_active_nodes": total_active_nodes,
            "total_vram_bytes": total_vram_bytes,
            "total_vram_gb": round(total_vram_bytes / (1024**3), 2),
            "total_tflops": round(total_tflops, 2),
            "clusters": clusters_summary,
        }

    def calculate_cross_cluster_plan(
        self,
        model_id: str,
        total_layers: int,
        model_vram_bytes: int,
    ) -> Dict[str, Any]:
        """Calculates multi-cluster sharding allocation across federated clusters."""
        capacity = self.get_federated_capacity()
        total_vram = capacity["total_vram_bytes"]

        feasible = total_vram >= model_vram_bytes
        if not feasible:
            return {
                "model_id": model_id,
                "feasible": False,
                "reason": f"Insufficient federated VRAM: required {model_vram_bytes / (1024**3):.2f} GB, available {total_vram / (1024**3):.2f} GB",
                "cluster_assignments": [],
            }

        assignments = []
        current_layer = 0

        # Sort clusters by VRAM capacity descending
        sorted_clusters = sorted(
            [c for c in self._clusters.values() if c.total_vram_bytes > 0],
            key=lambda c: c.total_vram_bytes,
            reverse=True,
        )

        for cluster in sorted_clusters:
            if current_layer >= total_layers:
                break

            fraction = cluster.total_vram_bytes / total_vram
            assigned_layers = max(1, min(total_layers - current_layer, int(round(total_layers * fraction))))

            start = current_layer
            end = min(total_layers, start + assigned_layers)
            actual_assigned = end - start
            current_layer = end

            if actual_assigned > 0:
                allocated_vram = int(model_vram_bytes * (actual_assigned / total_layers))
                assignments.append(
                    {
                        "cluster_id": cluster.cluster_id,
                        "cluster_name": cluster.name,
                        "region": cluster.region,
                        "start_layer": start,
                        "end_layer": end,
                        "assigned_layers_count": actual_assigned,
                        "allocated_vram_gb": round(allocated_vram / (1024**3), 2),
                        "node_count": cluster.active_nodes_count,
                    }
                )

        # Catch any remaining layers
        if current_layer < total_layers and assignments:
            assignments[-1]["end_layer"] = total_layers
            assignments[-1]["assigned_layers_count"] += total_layers - current_layer

        return {
            "model_id": model_id,
            "feasible": True,
            "total_layers": total_layers,
            "federated_vram_gb": capacity["total_vram_gb"],
            "cluster_assignments": assignments,
        }


# Global instance
GLOBAL_MULTI_CLUSTER_FEDERATOR = MultiClusterFederator()
