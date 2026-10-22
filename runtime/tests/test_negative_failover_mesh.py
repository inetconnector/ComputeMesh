import unittest
from runtime.autonomous_failover_mesh import (
    EndToEndLatencyOptimizer,
    AutonomousFailoverMeshFabric,
)

class TestAutonomousFailoverMeshNegative(unittest.TestCase):
    def setUp(self) -> None:
        self.optimizer = EndToEndLatencyOptimizer()
        self.fabric = AutonomousFailoverMeshFabric(self.optimizer)

    def test_connect_to_invalid_node_fails(self) -> None:
        self.optimizer.register_route(
            "route_invalid", "node_invalid", "127.0.0.1", 12345, latency_ms=10.0, bandwidth_mbps=100.0
        )

        connected = self.fabric.connect_to_node("node_invalid")
        self.assertFalse(connected, "Connecting to an invalid node should fail (real network check needed)")

if __name__ == "__main__":
    unittest.main()
