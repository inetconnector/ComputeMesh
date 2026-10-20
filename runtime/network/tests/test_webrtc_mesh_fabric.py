#!/usr/bin/env python3
"""Tests for WebRTC P2P Mesh Fabric Resilience Subsystem."""
from __future__ import annotations

import socket
import tempfile
import time
import unittest
from pathlib import Path

from runtime.network.mesh_transport import generate_node_tls_credentials
from runtime.network.webrtc_mesh_fabric import (
    MeshFabricMetrics,
    ResilientMeshFabricManager,
    WebRTCFabricError,
    WebRTCFrameType,
    WebRTCP2PPeer,
    WebRTCP2PState,
    pack_frame,
    unpack_frame_header,
)


class TestWebRTCMeshFabric(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.tmp_dir = Path(self.tmp.name)
        self.node_a_creds = generate_node_tls_credentials("node-a", self.tmp_dir)
        self.node_b_creds = generate_node_tls_credentials("node-b", self.tmp_dir)

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_frame_pack_unpack_integrity(self) -> None:
        payload = b"ComputeMesh WebRTC Resilience Test Payload"
        seq = 42
        frame = pack_frame(WebRTCFrameType.DATA, seq, payload)
        ftype, unpacked_seq, plen, checksum = unpack_frame_header(frame[:17])
        self.assertEqual(ftype, WebRTCFrameType.DATA)
        self.assertEqual(unpacked_seq, seq)
        self.assertEqual(plen, len(payload))

    def test_p2p_peer_bidirectional_data_exchange(self) -> None:
        # Create connected socket pair
        sock_a, sock_b = socket.socketpair()

        peer_a = WebRTCP2PPeer(local_creds=self.node_a_creds, remote_node_id="node-b")
        peer_b = WebRTCP2PPeer(local_creds=self.node_b_creds, remote_node_id="node-a")

        received_a: list[bytes] = []
        received_b: list[bytes] = []

        peer_a.set_data_callback(lambda d: received_a.append(d))
        peer_b.set_data_callback(lambda d: received_b.append(d))

        peer_a.attach_socket(sock_a)
        peer_b.attach_socket(sock_b)

        time.sleep(0.1)
        self.assertEqual(peer_a.state, WebRTCP2PState.CONNECTED)
        self.assertEqual(peer_b.state, WebRTCP2PState.CONNECTED)

        # Peer A -> Peer B
        peer_a.send_data(b"Hello Node B from Node A")
        # Peer B -> Peer A
        peer_b.send_data(b"Hello Node A from Node B")

        time.sleep(0.3)

        self.assertIn(b"Hello Node B from Node A", received_b)
        self.assertIn(b"Hello Node A from Node B", received_a)

        peer_a.close()
        peer_b.close()

    def test_resilient_fabric_manager_failover_to_mtls(self) -> None:
        mgr_a = ResilientMeshFabricManager(self.node_a_creds)

        # Mock mTLS fallback target socket
        fallback_sock_a, fallback_sock_b = socket.socketpair()
        mgr_a.register_mtls_fallback("node-b", fallback_sock_a)

        # When no P2P peer is registered, send_to_peer should fall back to mTLS
        transport = mgr_a.send_to_peer("node-b", b"Fallback payload")
        self.assertEqual(transport, "mtls_fallback")

        recv_fallback = fallback_sock_b.recv(1024)
        self.assertEqual(recv_fallback, b"Fallback payload")

        # Now attach a P2P peer
        sock_a, sock_b = socket.socketpair()
        peer_a = mgr_a.register_peer_p2p("node-b", sock_a)
        peer_b = WebRTCP2PPeer(local_creds=self.node_b_creds, remote_node_id="node-a")
        peer_b.attach_socket(sock_b)

        time.sleep(0.1)

        # Active healthy P2P peer should be preferred
        transport_p2p = mgr_a.send_to_peer("node-b", b"P2P payload")
        self.assertEqual(transport_p2p, "webrtc_p2p")

        # Force P2P peer into failed state
        sock_b.close()
        time.sleep(0.3)

        # Subsequent send should failover to mTLS
        transport_after_fail = mgr_a.send_to_peer("node-b", b"Fallback after P2P fail")
        self.assertEqual(transport_after_fail, "mtls_fallback")

        metrics = mgr_a.get_peer_metrics("node-b")
        self.assertGreater(metrics.failover_count, 0)

        mgr_a.close_all()
        peer_b.close()
        fallback_sock_a.close()
        fallback_sock_b.close()


if __name__ == "__main__":
    unittest.main()
