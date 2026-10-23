import unittest
import multiprocessing
import socket
import time
import json
from runtime.autonomous_failover_mesh import (
    EndToEndLatencyOptimizer,
    AutonomousFailoverMeshFabric,
)

def run_real_node_server(
    port_queue: multiprocessing.Queue,
    stop_event: multiprocessing.Event,
    simulate_wrong_node: bool = False,
    simulate_missing_session: bool = False,
    simulate_wrong_session: bool = False,
    simulate_oversize: bool = False,
    simulate_stall: bool = False,
    simulate_fragmented: bool = False
):
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    port_queue.put(port)
    sock.listen(1)
    sock.settimeout(0.5)
    while not stop_event.is_set():
        try:
            conn, addr = sock.accept()
            with conn:
                if simulate_stall:
                    # Accept connection but do not read or send anything
                    time.sleep(2.5)
                    continue

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
                            if simulate_oversize:
                                resp = {"type": "ACK", "padding": "X" * 5000}
                            else:
                                resp = {
                                    "type": "ACK",
                                    "session_id": req.get("session_id") if not simulate_wrong_session else "wrong_session",
                                    "request_id": req.get("request_id"),
                                    "target_node_id": req.get("target_node_id") if not simulate_wrong_node else "wrong_node_id"
                                }
                                if simulate_missing_session:
                                    del resp["session_id"]

                            resp_bytes = json.dumps(resp).encode('utf-8')

                            if simulate_fragmented:
                                # Send partial, sleep, send rest without newline
                                conn.sendall(resp_bytes[:10])
                                time.sleep(0.5)
                                conn.sendall(resp_bytes[10:])
                            else:
                                conn.sendall(resp_bytes + b'\n')
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
        self.stop_event_missing_session = multiprocessing.Event()
        self.stop_event_wrong_session = multiprocessing.Event()
        self.stop_event_oversize = multiprocessing.Event()
        self.stop_event_stall = multiprocessing.Event()
        self.stop_event_fragmented = multiprocessing.Event()

        self.q1 = multiprocessing.Queue()
        self.q2 = multiprocessing.Queue()
        self.q3 = multiprocessing.Queue()
        self.q_missing_session = multiprocessing.Queue()
        self.q_wrong_session = multiprocessing.Queue()
        self.q_oversize = multiprocessing.Queue()
        self.q_stall = multiprocessing.Queue()
        self.q_fragmented = multiprocessing.Queue()

        self.server1 = multiprocessing.Process(target=run_real_node_server, args=(self.q1, self.stop_event1))
        self.server2 = multiprocessing.Process(target=run_real_node_server, args=(self.q2, self.stop_event2))
        self.server3 = multiprocessing.Process(target=run_real_node_server, kwargs={"port_queue": self.q3, "stop_event": self.stop_event3, "simulate_wrong_node": True})
        self.server_missing_session = multiprocessing.Process(target=run_real_node_server, kwargs={"port_queue": self.q_missing_session, "stop_event": self.stop_event_missing_session, "simulate_missing_session": True})
        self.server_wrong_session = multiprocessing.Process(target=run_real_node_server, kwargs={"port_queue": self.q_wrong_session, "stop_event": self.stop_event_wrong_session, "simulate_wrong_session": True})
        self.server_oversize = multiprocessing.Process(target=run_real_node_server, kwargs={"port_queue": self.q_oversize, "stop_event": self.stop_event_oversize, "simulate_oversize": True})
        self.server_stall = multiprocessing.Process(target=run_real_node_server, kwargs={"port_queue": self.q_stall, "stop_event": self.stop_event_stall, "simulate_stall": True})
        self.server_fragmented = multiprocessing.Process(target=run_real_node_server, kwargs={"port_queue": self.q_fragmented, "stop_event": self.stop_event_fragmented, "simulate_fragmented": True})

        self.server1.start()
        self.server2.start()
        self.server3.start()
        self.server_missing_session.start()
        self.server_wrong_session.start()
        self.server_oversize.start()
        self.server_stall.start()
        self.server_fragmented.start()

        self.port1 = self.q1.get(timeout=2.0)
        self.port2 = self.q2.get(timeout=2.0)
        self.port3 = self.q3.get(timeout=2.0)
        self.port_missing_session = self.q_missing_session.get(timeout=2.0)
        self.port_wrong_session = self.q_wrong_session.get(timeout=2.0)
        self.port_oversize = self.q_oversize.get(timeout=2.0)
        self.port_stall = self.q_stall.get(timeout=2.0)
        self.port_fragmented = self.q_fragmented.get(timeout=2.0)

        self.optimizer = EndToEndLatencyOptimizer()
        self.fabric = AutonomousFailoverMeshFabric(self.optimizer)

    def tearDown(self):
        self.stop_event1.set()
        self.stop_event2.set()
        self.stop_event3.set()
        self.stop_event_missing_session.set()
        self.stop_event_wrong_session.set()
        self.stop_event_oversize.set()
        self.stop_event_stall.set()
        self.stop_event_fragmented.set()

        for p in (
            self.server1, self.server2, self.server3,
            self.server_missing_session, self.server_wrong_session,
            self.server_oversize, self.server_stall, self.server_fragmented
        ):
            p.join(timeout=1.0)
            if p.is_alive():
                p.terminate()
                p.join(timeout=1.0)

    def test_real_connection_and_failover(self):
        self.optimizer.register_route("route_A", "node_1", "127.0.0.1", self.port1, latency_ms=20.0, bandwidth_mbps=100.0)
        self.optimizer.register_route("route_B", "node_1", "127.0.0.1", self.port2, latency_ms=50.0, bandwidth_mbps=100.0)

        # Initial connection should succeed to route_A (since it has lower latency)
        connected = self.fabric.connect_to_node("node_1")
        self.assertTrue(connected)
        self.assertEqual(self.fabric.active_connections.get("node_1"), "route_A_LOCAL_UNAUTHENTICATED_ONLY")

        # Kill server 1
        self.stop_event1.set()
        self.server1.join(timeout=1.0)
        if self.server1.is_alive():
            self.server1.terminate()

        # Trigger a reconnect logic
        connected2 = self.fabric.connect_to_node("node_1")
        self.assertTrue(connected2)
        self.assertEqual(self.fabric.active_connections.get("node_1"), "route_B_LOCAL_UNAUTHENTICATED_ONLY")

        self.assertEqual(len(self.fabric.failover_history), 1)
        self.assertFalse(self.optimizer._routes["route_A"].is_active)

    def test_negative_wrong_node_id_rejected(self):
        # route_C points to server3 which answers with wrong node_id
        self.optimizer.register_route("route_C", "node_1", "127.0.0.1", self.port3, latency_ms=10.0, bandwidth_mbps=100.0)

        connected = self.fabric.connect_to_node("node_1")
        self.assertFalse(connected)
        self.assertNotIn("node_1", self.fabric.active_connections)
        self.assertFalse(self.optimizer._routes["route_C"].is_active)

    def test_negative_missing_session_id_rejected(self):
        self.optimizer.register_route("route_missing", "node_1", "127.0.0.1", self.port_missing_session, latency_ms=10.0, bandwidth_mbps=100.0)
        connected = self.fabric.connect_to_node("node_1")
        self.assertFalse(connected)
        self.assertNotIn("node_1", self.fabric.active_connections)
        self.assertFalse(self.optimizer._routes["route_missing"].is_active)

    def test_negative_wrong_session_id_rejected(self):
        self.optimizer.register_route("route_wrong", "node_1", "127.0.0.1", self.port_wrong_session, latency_ms=10.0, bandwidth_mbps=100.0)
        connected = self.fabric.connect_to_node("node_1")
        self.assertFalse(connected)
        self.assertNotIn("node_1", self.fabric.active_connections)
        self.assertFalse(self.optimizer._routes["route_wrong"].is_active)

    def test_negative_oversize_response_rejected(self):
        self.optimizer.register_route("route_oversize", "node_1", "127.0.0.1", self.port_oversize, latency_ms=10.0, bandwidth_mbps=100.0)
        connected = self.fabric.connect_to_node("node_1")
        self.assertFalse(connected)
        self.assertNotIn("node_1", self.fabric.active_connections)
        self.assertFalse(self.optimizer._routes["route_oversize"].is_active)

    def test_negative_stall_timeout(self):
        self.optimizer.register_route("route_stall", "node_1", "127.0.0.1", self.port_stall, latency_ms=10.0, bandwidth_mbps=100.0)
        connected = self.fabric.connect_to_node("node_1")
        self.assertFalse(connected)
        self.assertNotIn("node_1", self.fabric.active_connections)
        self.assertFalse(self.optimizer._routes["route_stall"].is_active)

    def test_negative_fragmented_no_newline(self):
        self.optimizer.register_route("route_frag", "node_1", "127.0.0.1", self.port_fragmented, latency_ms=10.0, bandwidth_mbps=100.0)
        connected = self.fabric.connect_to_node("node_1")
        self.assertFalse(connected)
        self.assertNotIn("node_1", self.fabric.active_connections)
        self.assertFalse(self.optimizer._routes["route_frag"].is_active)


if __name__ == "__main__":
    unittest.main()
