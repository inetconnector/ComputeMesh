"""ComputeMesh Autonomous Failover Mesh Fabric & End-to-End Latency Optimization.

Provides self-healing mesh fabric with zero-downtime failover and dynamic
end-to-end latency optimization across distributed clusters.
"""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

log = logging.getLogger("computemesh.runtime.autonomous_failover")

@dataclass
class MeshRoute:
    """Represents a specific network path to a target node in the mesh."""
    route_id: str
    target_node_id: str
    latency_ms: float
    bandwidth_mbps: float
    error_rate: float
    is_active: bool = True
    last_probed_at: float = field(default_factory=time.time)


@dataclass
class OptimizationMetrics:
    """Metrics tracking the effectiveness of latency optimization."""
    total_routes_optimized: int = 0
    average_latency_improvement_ms: float = 0.0
    failover_events_triggered: int = 0


class EndToEndLatencyOptimizer:
    """Dynamically monitors and optimizes end-to-end latency across mesh routes."""

    def __init__(self) -> None:
        self._routes: Dict[str, MeshRoute] = {}
        self._metrics = OptimizationMetrics()

    def register_route(self, route_id: str, target_node_id: str, latency_ms: float, bandwidth_mbps: float) -> None:
        """Registers a new possible network route to a node."""
        self._routes[route_id] = MeshRoute(
            route_id=route_id,
            target_node_id=target_node_id,
            latency_ms=latency_ms,
            bandwidth_mbps=bandwidth_mbps,
            error_rate=0.0
        )

    def update_route_metrics(self, route_id: str, latency_ms: float, error_rate: float) -> None:
        """Updates route metrics based on real-time observations."""
        if route_id in self._routes:
            route = self._routes[route_id]
            old_latency = route.latency_ms
            # EWMA for latency
            route.latency_ms = (route.latency_ms * 0.7) + (latency_ms * 0.3)
            route.error_rate = error_rate
            route.last_probed_at = time.time()
            if old_latency > route.latency_ms:
                self._metrics.average_latency_improvement_ms += (old_latency - route.latency_ms)
                self._metrics.total_routes_optimized += 1

    def get_optimal_route(self, target_node_id: str) -> Optional[MeshRoute]:
        """Returns the best available route to a node based on latency and bandwidth."""
        candidates = [
            r for r in self._routes.values()
            if r.target_node_id == target_node_id and r.is_active and r.error_rate < 0.1
        ]
        if not candidates:
            return None

        # Priority: lowest latency, then highest bandwidth
        candidates.sort(key=lambda r: (r.latency_ms, -r.bandwidth_mbps))
        return candidates[0]


class AutonomousFailoverMeshFabric:
    """Provides self-healing connections and zero-downtime failover between nodes."""

    def __init__(self, latency_optimizer: EndToEndLatencyOptimizer) -> None:
        self.optimizer = latency_optimizer
        self.active_connections: Dict[str, str] = {} # target_node_id -> active route_id
        self.failover_history: List[Dict[str, Any]] = []

    def connect_to_node(self, target_node_id: str) -> bool:
        """Establishes connection to a node using the optimal route."""
        route = self.optimizer.get_optimal_route(target_node_id)
        if route:
            self.active_connections[target_node_id] = route.route_id
            return True
        return False

    def handle_connection_failure(self, target_node_id: str, failed_route_id: str) -> bool:
        """Handles connection drops by autonomously failing over to the next best route."""
        log.warning(f"Connection failure to {target_node_id} on route {failed_route_id}. Initiating failover...")
        if failed_route_id in self.optimizer._routes:
            self.optimizer._routes[failed_route_id].is_active = False
            self.optimizer._routes[failed_route_id].error_rate = 1.0

        self.optimizer._metrics.failover_events_triggered += 1

        new_route = self.optimizer.get_optimal_route(target_node_id)
        if new_route:
            self.active_connections[target_node_id] = new_route.route_id
            self.failover_history.append({
                "target_node": target_node_id,
                "failed_route": failed_route_id,
                "new_route": new_route.route_id,
                "timestamp": time.time()
            })
            log.info(f"Successfully failed over to route {new_route.route_id} for node {target_node_id}")
            return True
        else:
            log.error(f"Failover failed for {target_node_id}. No active routes available.")
            if target_node_id in self.active_connections:
                del self.active_connections[target_node_id]
            return False


GLOBAL_LATENCY_OPTIMIZER = EndToEndLatencyOptimizer()
GLOBAL_FAILOVER_FABRIC = AutonomousFailoverMeshFabric(GLOBAL_LATENCY_OPTIMIZER)
