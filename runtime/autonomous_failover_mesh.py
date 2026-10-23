"""ComputeMesh Autonomous Failover Mesh Fabric & End-to-End Latency Optimization.

Provides self-healing mesh fabric with zero-downtime failover and dynamic
end-to-end latency optimization across distributed clusters.
"""
from __future__ import annotations

import logging
import time
import socket
import json
import uuid
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

log = logging.getLogger("computemesh.runtime.autonomous_failover")

@dataclass
class MeshRoute:
    """Represents a specific network path to a target node in the mesh."""
    original_latency_ms: float = field(init=False)
    route_id: str
    target_node_id: str
    host: str
    port: int
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

    def register_route(self, route_id: str, target_node_id: str, host: str, port: int, latency_ms: float, bandwidth_mbps: float) -> None:
        """Registers a new possible network route to a node."""
        route = MeshRoute(
            route_id=route_id,
            target_node_id=target_node_id,
            host=host,
            port=port,
            latency_ms=latency_ms,
            bandwidth_mbps=bandwidth_mbps,
            error_rate=0.0
        )
        route.original_latency_ms = latency_ms
        self._routes[route_id] = route

    def update_route_metrics(self, route_id: str, latency_ms: float, error_rate: float) -> None:
        """Updates route metrics based on real-time observations."""
        if route_id in self._routes:
            route = self._routes[route_id]

            # EWMA for latency
            route.latency_ms = (route.latency_ms * 0.7) + (latency_ms * 0.3)
            route.error_rate = error_rate
            route.last_probed_at = time.time()

            # Recalculate metrics based on actual improvements over original baseline
            improved_routes = 0
            total_improvement = 0.0

            for r in self._routes.values():
                if r.latency_ms < r.original_latency_ms:
                    improved_routes += 1
                    total_improvement += (r.original_latency_ms - r.latency_ms)

            self._metrics.total_routes_optimized = improved_routes
            if improved_routes > 0:
                self._metrics.average_latency_improvement_ms = total_improvement / improved_routes
            else:
                self._metrics.average_latency_improvement_ms = 0.0

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


    def _perform_handshake(self, sock: socket.socket, target_node_id: str, timeout: float = 2.0) -> bool:
        request_id = str(uuid.uuid4())
        session_id = str(uuid.uuid4())

        req = {
            "type": "HANDSHAKE",
            "session_id": session_id,
            "node_id": "local-node",
            "request_id": request_id,
            "target_node_id": target_node_id
        }

        sock.settimeout(timeout)
        sock.sendall(json.dumps(req).encode('utf-8') + b'\n')

        response_data = b""
        start_time = time.time()
        while True:
            if time.time() - start_time > timeout:
                raise socket.timeout("Handshake timeout")
            chunk = sock.recv(1024)
            if not chunk:
                return False
            response_data += chunk
            if b'\n' in response_data:
                break

        try:
            resp = json.loads(response_data.decode('utf-8').strip())
            if resp.get("type") != "ACK":
                log.warning(f"Handshake failed: expected ACK, got {resp.get('type')}")
                return False
            if resp.get("request_id") != request_id:
                log.warning(f"Handshake failed: mismatch request_id {resp.get('request_id')} != {request_id}")
                return False
            if resp.get("target_node_id") != target_node_id:
                log.warning(f"Handshake failed: mismatch target_node_id {resp.get('target_node_id')} != {target_node_id}")
                return False
            return True
        except json.JSONDecodeError:
            log.warning("Handshake failed: invalid JSON response")
            return False

    def connect_to_node(self, target_node_id: str) -> bool:

        """Establishes connection to a node using the optimal route."""
        route = self.optimizer.get_optimal_route(target_node_id)
        if route:
            try:
                # Attempt an actual TCP connection
                with socket.create_connection((route.host, route.port), timeout=2.0) as sock:
                    if not self._perform_handshake(sock, target_node_id):
                        raise OSError("Handshake verification failed")
                self.active_connections[target_node_id] = route.route_id
                return True
            except (socket.timeout, ConnectionRefusedError, OSError) as e:
                log.warning(f"Failed to connect to {target_node_id} via {route.route_id}: {e}")
                # Update error rate and try failover immediately
                self.optimizer.update_route_metrics(route.route_id, latency_ms=route.latency_ms, error_rate=1.0)
                return self.handle_connection_failure(target_node_id, route.route_id)
        return False

    def handle_connection_failure(self, target_node_id: str, failed_route_id: str) -> bool:
        """Handles connection drops by autonomously failing over to the next best route."""
        log.warning(f"Connection failure to {target_node_id} on route {failed_route_id}. Initiating failover...")
        if failed_route_id in self.optimizer._routes:
            self.optimizer._routes[failed_route_id].is_active = False
            self.optimizer._routes[failed_route_id].error_rate = 1.0

        self.optimizer._metrics.failover_events_triggered += 1

        # A candidate route is NOT an established connection. Probe each eligible
        # replacement over TCP before recording success or changing active state.
        # Every failed replacement is removed from this attempt, preventing loops.
        while (new_route := self.optimizer.get_optimal_route(target_node_id)) is not None:
            try:
                with socket.create_connection((new_route.host, new_route.port), timeout=2.0) as sock:
                    if not self._perform_handshake(sock, target_node_id):
                        raise OSError("Handshake verification failed")
            except (socket.timeout, ConnectionRefusedError, OSError) as exc:
                log.warning("Replacement route %s failed its TCP probe: %s", new_route.route_id, type(exc).__name__)
                new_route.is_active = False
                new_route.error_rate = 1.0
                continue

            self.active_connections[target_node_id] = new_route.route_id
            self.failover_history.append({
                "target_node": target_node_id,
                "failed_route": failed_route_id,
                "new_route": new_route.route_id,
                "timestamp": time.time()
            })
            log.info("Verified TCP connection on replacement route %s", new_route.route_id)
            return True

        log.error("Failover failed for %s: no reachable replacement route.", target_node_id)
        self.active_connections.pop(target_node_id, None)
        return False


GLOBAL_LATENCY_OPTIMIZER = EndToEndLatencyOptimizer()
GLOBAL_FAILOVER_FABRIC = AutonomousFailoverMeshFabric(GLOBAL_LATENCY_OPTIMIZER)
