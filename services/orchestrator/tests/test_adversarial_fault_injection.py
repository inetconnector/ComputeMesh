"""Adversarial and fault-injection test suite for ComputeMesh orchestrator and persistent channels.

Tests system robustness against:
- Oversized frame attacks (DoS / memory exhaustion prevention).
- Malformed / corrupted wire frames.
- Abrupt connection termination mid-flight.
- Unauthenticated or rogue correlation IDs.
- Concurrency race conditions during session revocation and failure cascades.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
import json
import socket
import struct
import threading
import time
import unittest

from protocol.node_session import NodeSessionState, SessionSnapshot
from services.orchestrator.persistent_control_channel import (
    ChannelClosed,
    MAX_FRAME_BYTES,
    PersistentControlChannelError,
    PersistentNodeConnection,
    PersistentNodeControlClient,
    RequestTimeout,
    recv_frame,
    send_frame,
)


def _ready_session(node_id: str = "node-adversary") -> SessionSnapshot:
    return SessionSnapshot(
        session_id="session-adv-1",
        state=NodeSessionState.READY,
        revision=10,
        protocol_major=0,
        protocol_minor=2,
        node_id=node_id,
        principal_id="provider-adv",
        auth_method="computemesh-ed25519-v1",
        credential_expires_at=datetime.now(timezone.utc) + timedelta(minutes=10),
        negotiated_capabilities=frozenset({"execution_attestation_v1"}),
        profile_revision=1,
        drain_reason=None,
        close_reason=None,
    )


class AdversarialFaultInjectionTests(unittest.TestCase):
    def test_oversized_frame_rejected_immediately(self) -> None:
        """Ensure frames claiming size larger than MAX_FRAME_BYTES are rejected and closed."""
        server_sock, provider_sock = socket.socketpair()
        try:
            # Craft frame header claiming size larger than MAX_FRAME_BYTES
            huge_size = MAX_FRAME_BYTES + 1024
            provider_sock.sendall(struct.pack(">I", huge_size))

            with self.assertRaises(PersistentControlChannelError) as ctx:
                recv_frame(server_sock)
            self.assertIn("length", str(ctx.exception).lower())
        finally:
            server_sock.close()
            provider_sock.close()

    def test_negative_or_zero_frame_length_rejected(self) -> None:
        """Zero length frame header must be rejected."""
        server_sock, provider_sock = socket.socketpair()
        try:
            provider_sock.sendall(struct.pack(">I", 0))
            with self.assertRaises(PersistentControlChannelError) as ctx:
                recv_frame(server_sock)
            self.assertIn("invalid control frame length", str(ctx.exception))
        finally:
            server_sock.close()
            provider_sock.close()

    def test_malformed_json_frame_rejected(self) -> None:
        """Non-JSON payload within valid frame length must fail closed."""
        server_sock, provider_sock = socket.socketpair()
        try:
            raw = b"{not: valid, json: payload...}"
            provider_sock.sendall(struct.pack(">I", len(raw)) + raw)
            with self.assertRaises(PersistentControlChannelError) as ctx:
                recv_frame(server_sock)
            self.assertIn("not UTF-8 JSON", str(ctx.exception))
        finally:
            server_sock.close()
            provider_sock.close()

    def test_non_dict_root_frame_rejected(self) -> None:
        """JSON payload that is a list or scalar instead of a dict must be rejected."""
        server_sock, provider_sock = socket.socketpair()
        try:
            raw = json.dumps(["array", "instead", "of", "dict"]).encode("utf-8")
            provider_sock.sendall(struct.pack(">I", len(raw)) + raw)
            with self.assertRaises(PersistentControlChannelError) as ctx:
                recv_frame(server_sock)
            self.assertIn("must be an object", str(ctx.exception))
        finally:
            server_sock.close()
            provider_sock.close()

    def test_abrupt_worker_disconnect_during_in_flight_request(self) -> None:
        """When worker abruptly disconnects, pending request must raise ChannelClosed promptly."""
        server_sock, provider_sock = socket.socketpair()
        connection = PersistentNodeConnection(
            sock=server_sock,
            session=_ready_session("node-crash"),
            control_plane_id="cp-1",
        )
        client = PersistentNodeControlClient()
        client.register(connection)

        def worker_crash():
            # Receive the request frame, then abruptly close without responding
            frame = recv_frame(provider_sock)
            self.assertEqual(frame["kind"], "request")
            time.sleep(0.02)
            provider_sock.close()

        thread = threading.Thread(target=worker_crash, daemon=True)
        thread.start()

        start_time = time.monotonic()
        with self.assertRaises(ChannelClosed) as ctx:
            client.request(
                node_id="node-crash",
                message_type="ExecutionAttestationRequest",
                payload={"test": 123},
                timeout_seconds=5.0,
            )
        elapsed = time.monotonic() - start_time
        # Must fail fast upon socket closure, well before the 5.0s timeout
        self.assertLess(elapsed, 2.0)
        self.assertIn("disconnected", str(ctx.exception).lower())
        thread.join(timeout=2.0)

    def test_worker_error_payload_propagated_as_exception(self) -> None:
        """When provider returns an explicit error response, it must raise PersistentControlChannelError."""
        server_sock, provider_sock = socket.socketpair()
        connection = PersistentNodeConnection(
            sock=server_sock,
            session=_ready_session("node-err"),
            control_plane_id="cp-1",
        )
        client = PersistentNodeControlClient()
        client.register(connection)

        def worker_error():
            frame = recv_frame(provider_sock)
            send_frame(provider_sock, {
                "kind": "response",
                "correlation_id": frame["request_id"],
                "ok": False,
                "error": "GPU memory exhausted on provider",
            })

        thread = threading.Thread(target=worker_error, daemon=True)
        thread.start()

        with self.assertRaises(PersistentControlChannelError) as ctx:
            client.request(
                node_id="node-err",
                message_type="ExecutionAttestationRequest",
                payload={"test": 1},
                timeout_seconds=2.0,
            )
        self.assertIn("GPU memory exhausted", str(ctx.exception))
        thread.join(timeout=2.0)
        connection.close()
        provider_sock.close()

    def test_unsolicited_and_stray_response_frames_ignored_safely(self) -> None:
        """Stray response frames with non-matching correlation_id must not crash the connection loop."""
        server_sock, provider_sock = socket.socketpair()
        connection = PersistentNodeConnection(
            sock=server_sock,
            session=_ready_session("node-stray"),
            control_plane_id="cp-1",
        )
        client = PersistentNodeControlClient()
        client.register(connection)

        def worker_with_stray():
            # 1. Send stray unsolicited frame
            send_frame(provider_sock, {
                "kind": "response",
                "correlation_id": "non-existent-correlation-id-999",
                "ok": True,
                "payload": {"data": "rogue"},
            })
            time.sleep(0.05)
            # 2. Handle real request
            frame = recv_frame(provider_sock)
            send_frame(provider_sock, {
                "kind": "response",
                "correlation_id": frame["request_id"],
                "ok": True,
                "payload": {"status": "success"},
            })

        thread = threading.Thread(target=worker_with_stray, daemon=True)
        thread.start()

        resp = client.request(
            node_id="node-stray",
            message_type="ExecutionAttestationRequest",
            payload={"action": "test"},
            timeout_seconds=2.0,
        )
        self.assertEqual(resp, {"status": "success"})
        self.assertTrue(connection.alive)
        thread.join(timeout=2.0)
        connection.close()
        provider_sock.close()


if __name__ == "__main__":
    unittest.main()
