import unittest
import multiprocessing
import socket
import time
import json
from runtime.autonomous_failover_mesh import (
    EndToEndLatencyOptimizer,
    AutonomousFailoverMeshFabric,
)

def run_real_node_server(port: int, stop_event: multiprocessing.Event, simulate_wrong_node: bool = False):
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock.bind(("127.0.0.1", port))
    sock.listen(1)
    sock.settimeout(0.5)
    while not stop_event.is_set():
        try:
            conn, addr = sock.accept()
            with conn:
                data = b""
                conn.settimeout(1.0)
                while True:
                    try:
                        chunk = conn.recv(1024)
                        if not chunk:
                            break
                        data += chunk
                        if b'\n' in data:
                            break
                    except socket.timeout:
                        break
                if data:
                    try:
                        req = json.loads(data.decode('utf-8').strip())
                        if req.get("type") == "HANDSHAKE":
                            resp = {
                                "type": "ACK",
                                "request_id": req.get("request_id"),
                                "target_node_id": req.get("target_node_id") if not simulate_wrong_node else "wrong_node_id"
                            }
                            conn.sendall(json.dumps(resp).encode('utf-8') + b'\n')
                    except json.JSONDecodeError:
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
        self.stop_event3 = multiprocessing.Event()

        self.server1 = multiprocessing.Process(target=run_real_node_server, args=(12348, self.stop_event1))
        self.server2 = multiprocessing.Process(target=run_real_node_server, args=(12349, self.stop_event2))
        self.server3 = multiprocessing.Process(target=run_real_node_server, args=(12350, self.stop_event3, True)) # simulates wrong node

        self.server1.start()
        self.server2.start()
        self.server3.start()

        self.optimizer = EndToEndLatencyOptimizer()
        self.fabric = AutonomousFailoverMeshFabric(self.optimizer)

        # Give servers a moment to bind
        time.sleep(0.1)

    def tearDown(self):
        self.stop_event1.set()
        self.stop_event2.set()
        self.stop_event3.set()
        self.server1.join(timeout=1.0)
        self.server2.join(timeout=1.0)
        self.server3.join(timeout=1.0)
        if self.server1.is_alive():
            self.server1.terminate()
        if self.server2.is_alive():
            self.server2.terminate()
        if self.server3.is_alive():
            self.server3.terminate()

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

    def test_negative_wrong_node_id_rejected(self):
        # route_C points to server3 which answers with wrong node_id
        self.optimizer.register_route("route_C", "node_1", "127.0.0.1", 12350, latency_ms=10.0, bandwidth_mbps=100.0)

        connected = self.fabric.connect_to_node("node_1")
        self.assertFalse(connected)
        self.assertNotIn("node_1", self.fabric.active_connections)
        self.assertFalse(self.optimizer._routes["route_C"].is_active)


if __name__ == "__main__":
    unittest.main()
