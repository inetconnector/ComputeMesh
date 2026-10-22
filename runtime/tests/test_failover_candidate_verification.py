"""Regression: candidate selection must not masquerade as failover success.

Uses an OS-reserved loopback port with no listener, not a mocked socket.
A real local TCP endpoint is tested separately in test_multiprocess_failover_mesh.
"""
import socket
import unittest

from runtime.autonomous_failover_mesh import (
    AutonomousFailoverMeshFabric,
    EndToEndLatencyOptimizer,
)


class TestFailoverCandidateVerification(unittest.TestCase):
    def test_unreachable_backup_must_not_be_promoted(self):
        optimizer = EndToEndLatencyOptimizer()
        fabric = AutonomousFailoverMeshFabric(optimizer)

        # Reserve the port so no external listener can accept connections.
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as unavailable:
            unavailable.bind(("127.0.0.1", 0))
            port = unavailable.getsockname()[1]
            optimizer.register_route("primary", "target", "127.0.0.1", port, 10.0, 100.0)
            optimizer.register_route("backup", "target", "127.0.0.1", port, 20.0, 100.0)
            fabric.active_connections["target"] = "primary"

            self.assertFalse(fabric.handle_connection_failure("target", "primary"))
            self.assertNotIn("target", fabric.active_connections)
            self.assertFalse(optimizer._routes["backup"].is_active)
            self.assertEqual(fabric.failover_history, [])

    def test_primary_and_backup_unreachable_is_not_success(self):
        optimizer = EndToEndLatencyOptimizer()
        fabric = AutonomousFailoverMeshFabric(optimizer)
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as unavailable:
            unavailable.bind(("127.0.0.1", 0))
            port = unavailable.getsockname()[1]
            optimizer.register_route("a", "n", "127.0.0.1", port, 10.0, 100.0)
            optimizer.register_route("b", "n", "127.0.0.1", port, 20.0, 100.0)
            self.assertFalse(fabric.connect_to_node("n"))
            self.assertEqual(fabric.failover_history, [])


if __name__ == "__main__":
    unittest.main()
