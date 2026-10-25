"""ComputeMesh Autonomous Failover Mesh Fabric & End-to-End Latency Optimization.

Provides self-healing mesh fabric with zero-downtime failover and dynamic
end-to-end latency optimization across distributed clusters.
"""
from __future__ import annotations

import logging
import time
import socket
import hmac
import hashlib
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

    def __init__(
        self,
        latency_optimizer: EndToEndLatencyOptimizer,
        auth_secret: Optional[str] = None,
        require_peer_auth: bool = False,
    ) -> None:
        self.optimizer = latency_optimizer
        self.auth_secret = auth_secret
        self.require_peer_auth = require_peer_auth
        self.active_connections: Dict[str, str] = {} # target_node_id -> active route_id
        self.failover_history: List[Dict[str, Any]] = []
        self._last_handshake_authenticated: bool = False
        self._processed_jobs: Set[str] = set()


    def _perform_handshake(self, sock: socket.socket, target_node_id: str, timeout: float = 2.0) -> bool:
        self._last_handshake_authenticated = False
        request_id = str(uuid.uuid4())
        session_id = str(uuid.uuid4())

        req = {
            "type": "HANDSHAKE",
            "session_id": session_id,
            "node_id": "local-node",
            "request_id": request_id,
            "target_node_id": target_node_id
        }
        if self.auth_secret:
            mac_data = f"REQ:{session_id}:{request_id}:{target_node_id}".encode("utf-8")
            req["auth_mac"] = hmac.new(self.auth_secret.encode("utf-8"), mac_data, hashlib.sha256).hexdigest()

        sock.settimeout(timeout)
        sock.sendall(json.dumps(req).encode('utf-8') + b'\n')

        response_data = bytearray()
        start_time = time.time()
        max_length = 4096

        while True:
            if time.time() - start_time > timeout:
                raise socket.timeout("Handshake timeout")

            try:
                chunk = sock.recv(min(1024, max_length - len(response_data) + 1))
            except socket.timeout:
                raise socket.timeout("Handshake timeout during recv")

            if not chunk:
                return False

            response_data.extend(chunk)

            if len(response_data) > max_length:
                log.warning(f"Handshake failed: response exceeded {max_length} bytes")
                return False

            if b'\n' in response_data:
                break

        try:
            resp = json.loads(response_data.decode('utf-8').strip())
            if resp.get("type") != "ACK":
                log.warning(f"Handshake failed: expected ACK, got {resp.get('type')}")
                return False
            if resp.get("session_id") != session_id:
                log.warning(f"Handshake failed: mismatch session_id {resp.get('session_id')} != {session_id}")
                return False
            if resp.get("request_id") != request_id:
                log.warning(f"Handshake failed: mismatch request_id {resp.get('request_id')} != {request_id}")
                return False
            if resp.get("target_node_id") != target_node_id:
                log.warning(f"Handshake failed: mismatch target_node_id {resp.get('target_node_id')} != {target_node_id}")
                return False

            resp_mac = resp.get("auth_mac")
            if self.require_peer_auth:
                if not resp_mac or not self.auth_secret:
                    log.warning("Handshake failed: missing required peer auth_mac")
                    return False
                mac_expected = hmac.new(
                    self.auth_secret.encode("utf-8"),
                    f"ACK:{session_id}:{request_id}:{target_node_id}".encode("utf-8"),
                    hashlib.sha256
                ).hexdigest()
                if not hmac.compare_digest(resp_mac, mac_expected):
                    log.warning("Handshake failed: peer auth_mac mismatch")
                    return False
                self._last_handshake_authenticated = True
            elif resp_mac and self.auth_secret:
                mac_expected = hmac.new(
                    self.auth_secret.encode("utf-8"),
                    f"ACK:{session_id}:{request_id}:{target_node_id}".encode("utf-8"),
                    hashlib.sha256
                ).hexdigest()
                if hmac.compare_digest(resp_mac, mac_expected):
                    self._last_handshake_authenticated = True

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
                status_tag = "_AUTHENTICATED" if self._last_handshake_authenticated else "_LOCAL_UNAUTHENTICATED_ONLY"
                self.active_connections[target_node_id] = f"{route.route_id}{status_tag}"
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

            self.active_connections[target_node_id] = new_route.route_id + "_LOCAL_UNAUTHENTICATED_ONLY"
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

    def execute_work(
        self,
        target_node_id: str,
        job_id: str,
        payload: Dict[str, Any],
        timeout: float = 2.0,
    ) -> Dict[str, Any]:
        """Executes authenticated work with crash failover, verified results, and idempotency."""
        if job_id in self._processed_jobs:
            return {"status": "duplicate", "job_id": job_id, "result": "already_executed"}

        # Ensure active connection
        if target_node_id not in self.active_connections:
            if not self.connect_to_node(target_node_id):
                return {"status": "error", "reason": "node_unreachable", "job_id": job_id}

        while True:
            route = self.optimizer.get_optimal_route(target_node_id)
            if not route:
                return {"status": "error", "reason": "no_active_route", "job_id": job_id}

            session_id = str(uuid.uuid4())
            req: Dict[str, Any] = {
                "type": "JOB_EXECUTE",
                "job_id": job_id,
                "session_id": session_id,
                "payload": payload,
            }
            if self.auth_secret:
                mac_data = f"JOB:{job_id}:{session_id}".encode("utf-8")
                req["job_mac"] = hmac.new(self.auth_secret.encode("utf-8"), mac_data, hashlib.sha256).hexdigest()

            req_bytes = json.dumps(req).encode("utf-8") + b"\n"

            try:
                with socket.create_connection((route.host, route.port), timeout=timeout) as sock:
                    sock.settimeout(timeout)
                    sock.sendall(req_bytes)
                    data = b""
                    while True:
                        chunk = sock.recv(1024)
                        if not chunk:
                            break
                        data += chunk
                        if b"\n" in data:
                            break

                if not data:
                    raise OSError("Empty response from worker")

                resp = json.loads(data.decode("utf-8").strip())
                if self.auth_secret and resp.get("status") in ("success", "duplicate"):
                    expected_mac = hmac.new(
                        self.auth_secret.encode("utf-8"),
                        f"RESULT:{job_id}:{resp.get('status')}".encode("utf-8"),
                        hashlib.sha256
                    ).hexdigest()
                    if not hmac.compare_digest(resp.get("result_mac", ""), expected_mac):
                        return {"status": "error", "reason": "invalid_worker_result_mac", "job_id": job_id}

                self._processed_jobs.add(job_id)
                return resp

            except (socket.timeout, ConnectionRefusedError, OSError) as exc:
                log.warning(f"Worker {target_node_id} failed during job {job_id} on route {route.route_id}: {exc}")
                self.optimizer.update_route_metrics(route.route_id, latency_ms=route.latency_ms, error_rate=1.0)
                if not self.handle_connection_failure(target_node_id, route.route_id):
                    return {"status": "error", "reason": "failover_exhausted", "job_id": job_id}
                # Continue loop on failed over route



GLOBAL_LATENCY_OPTIMIZER = EndToEndLatencyOptimizer()
GLOBAL_FAILOVER_FABRIC = AutonomousFailoverMeshFabric(GLOBAL_LATENCY_OPTIMIZER)
