"""Unit tests for Autonomous Failover Mesh Fabric & End-to-End Latency Optimization."""
from __future__ import annotations

import unittest
from runtime.autonomous_failover_mesh import (
    EndToEndLatencyOptimizer,
    AutonomousFailoverMeshFabric,
)

class TestAutonomousFailoverMesh(unittest.TestCase):
    def setUp(self) -> None:
        self.optimizer = EndToEndLatencyOptimizer()
        self.fabric = AutonomousFailoverMeshFabric(self.optimizer)

    def test_latency_optimization_route_selection(self) -> None:
        self.optimizer.register_route("route_A", "node_1", "127.0.0.1", 12345, latency_ms=50.0, bandwidth_mbps=100.0)
        self.optimizer.register_route("route_B", "node_1", "127.0.0.1", 12346, latency_ms=20.0, bandwidth_mbps=50.0)
        self.optimizer.register_route("route_C", "node_1", "127.0.0.1", 12347, latency_ms=20.0, bandwidth_mbps=200.0)

        best_route = self.optimizer.get_optimal_route("node_1")
        self.assertIsNotNone(best_route)
        self.assertEqual(best_route.route_id, "route_C")

    def test_latency_update(self) -> None:
        self.optimizer.register_route("route_A", "node_1", "127.0.0.1", 12345, latency_ms=50.0, bandwidth_mbps=100.0)
        self.optimizer.update_route_metrics("route_A", latency_ms=10.0, error_rate=0.0)

        route = self.optimizer._routes["route_A"]
        # 50 * 0.7 + 10 * 0.3 = 35 + 3 = 38
        self.assertAlmostEqual(route.latency_ms, 38.0)
        self.assertGreater(self.optimizer._metrics.total_routes_optimized, 0)
        self.assertGreater(self.optimizer._metrics.average_latency_improvement_ms, 0)

    def test_failover_no_routes_available(self) -> None:
        self.optimizer.register_route("route_A", "node_1", "127.0.0.1", 12345, latency_ms=20.0, bandwidth_mbps=100.0)
        self.fabric.connect_to_node("node_1")
        failed_over = self.fabric.handle_connection_failure("node_1", "route_A")
        self.assertFalse(failed_over)
        self.assertNotIn("node_1", self.fabric.active_connections)

if __name__ == "__main__":
    unittest.main()
