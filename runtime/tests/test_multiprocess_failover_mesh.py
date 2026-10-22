import unittest
import multiprocessing
import socket
import time
from runtime.autonomous_failover_mesh import (
    EndToEndLatencyOptimizer,
    AutonomousFailoverMeshFabric,
)

def run_real_node_server(port: int, stop_event: multiprocessing.Event):
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock.bind(("127.0.0.1", port))
    sock.listen(1)
    sock.settimeout(0.5)
    while not stop_event.is_set():
        try:
            conn, addr = sock.accept()
            with conn:
                data = conn.recv(1024)
                if data:
                    pass
        except socket.timeout:
            continue
        except OSError:
            break
    sock.close()

class TestMultiprocessFailoverMesh(unittest.TestCase):
    def setUp(self):
        self.stop_event1 = multiprocessing.Event()
        self.stop_event2 = multiprocessing.Event()

        self.server1 = multiprocessing.Process(target=run_real_node_server, args=(12348, self.stop_event1))
        self.server2 = multiprocessing.Process(target=run_real_node_server, args=(12349, self.stop_event2))

        self.server1.start()
        self.server2.start()

        self.optimizer = EndToEndLatencyOptimizer()
        self.fabric = AutonomousFailoverMeshFabric(self.optimizer)

        # Give servers a moment to bind
        time.sleep(0.1)

    def tearDown(self):
        self.stop_event1.set()
        self.stop_event2.set()
        self.server1.join(timeout=1.0)
        self.server2.join(timeout=1.0)
        if self.server1.is_alive():
            self.server1.terminate()
        if self.server2.is_alive():
            self.server2.terminate()

    def test_real_connection_and_failover(self):
        self.optimizer.register_route("route_A", "node_1", "127.0.0.1", 12348, latency_ms=20.0, bandwidth_mbps=100.0)
        self.optimizer.register_route("route_B", "node_1", "127.0.0.1", 12349, latency_ms=50.0, bandwidth_mbps=100.0)

        # Initial connection should succeed to route_A (since it has lower latency)
        connected = self.fabric.connect_to_node("node_1")
        self.assertTrue(connected)
        self.assertEqual(self.fabric.active_connections.get("node_1"), "route_A")

        # Kill server 1
        self.stop_event1.set()
        self.server1.join(timeout=1.0)
        if self.server1.is_alive():
            self.server1.terminate()

        # Trigger a reconnect logic
        connected2 = self.fabric.connect_to_node("node_1")
        self.assertTrue(connected2)
        self.assertEqual(self.fabric.active_connections.get("node_1"), "route_B")

        self.assertEqual(len(self.fabric.failover_history), 1)
        self.assertFalse(self.optimizer._routes["route_A"].is_active)

if __name__ == "__main__":
    unittest.main()
