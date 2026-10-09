from __future__ import annotations

import socket
import threading
import time
import unittest
from datetime import datetime, timedelta, timezone

from protocol.node_session import NodeSessionState, SessionSnapshot
from services.orchestrator.persistent_control_channel import (
    ChannelClosed,
    PersistentNodeConnection,
    PersistentNodeControlClient,
    ProviderPersistentClient,
    RequestCancelled,
    recv_frame,
    send_frame,
)


def ready_session(node_id: str = "node-a") -> SessionSnapshot:
    return SessionSnapshot(
        session_id="session-a",
        state=NodeSessionState.READY,
        revision=5,
        protocol_major=0,
        protocol_minor=2,
        node_id=node_id,
        principal_id="provider-a",
        auth_method="computemesh-ed25519-v1",
        credential_expires_at=datetime.now(timezone.utc) + timedelta(minutes=10),
        negotiated_capabilities=frozenset({"execution_attestation_v1"}),
        profile_revision=3,
        drain_reason=None,
        close_reason=None,
    )


class PersistentControlChannelTests(unittest.TestCase):
    def test_cancel_pending_request_notifies_provider_and_unblocks_caller(self):
        server_sock, provider_sock = socket.socketpair()
        connection = PersistentNodeConnection(sock=server_sock, session=ready_session(), control_plane_id="cp-1")
        client = PersistentNodeControlClient()
        client.register(connection)
        received = threading.Event()
        cancel_seen = threading.Event()

        def provider():
            frame = recv_frame(provider_sock)
            self.assertEqual(frame["request_id"], "req-cancel")
            received.set()
            cancel = recv_frame(provider_sock)
            self.assertEqual(cancel["kind"], "cancel")
            self.assertEqual(cancel["request_id"], "req-cancel")
            cancel_seen.set()

        provider_thread = threading.Thread(target=provider)
        provider_thread.start()
        result: list[BaseException] = []

        def request():
            try:
                client.request(
                    node_id="node-a",
                    message_type="InferenceRequest",
                    payload={},
                    timeout_seconds=2,
                    request_id="req-cancel",
                )
            except BaseException as exc:
                result.append(exc)

        request_thread = threading.Thread(target=request)
        request_thread.start()
        self.assertTrue(received.wait(1))
        self.assertTrue(client.cancel(node_id="node-a", request_id="req-cancel"))
        request_thread.join(1)
        provider_thread.join(1)
        self.assertTrue(cancel_seen.is_set())
        self.assertEqual(len(result), 1)
        self.assertIsInstance(result[0], RequestCancelled)
        connection.close()
        provider_sock.close()

    def test_provider_client_processes_cancel_while_handler_is_running(self):
        control_sock, provider_sock = socket.socketpair()
        started = threading.Event()

        def handler(message_type, payload, session, cancel_event):
            started.set()
            self.assertTrue(cancel_event.wait(1))
            raise RequestCancelled("cancelled by test")

        client = ProviderPersistentClient(
            connector=lambda: provider_sock,
            handshake=lambda sock, challenge: ready_session(),
            request_handler=handler,
            min_backoff_seconds=0.01,
            max_backoff_seconds=0.01,
        )
        thread = threading.Thread(target=client.serve_forever)
        thread.start()
        send_frame(control_sock, {"kind": "challenge", "session_id": "session-a", "challenge": "challenge", "control_plane_id": "cp-1"})
        send_frame(control_sock, {
            "kind": "request",
            "request_id": "running-1",
            "message_type": "InferenceRequest",
            "payload": {},
            "session_id": "session-a",
            "session_revision": 5,
        })
        self.assertTrue(started.wait(1))
        send_frame(control_sock, {"kind": "cancel", "request_id": "running-1", "reason": "user_cancelled"})
        response = recv_frame(control_sock)
        self.assertFalse(response["ok"])
        self.assertIn("cancel", response["error"].lower())
        client.stop()
        control_sock.close()
        provider_sock.close()
        thread.join(2)

    def test_provider_client_stop_unblocks_a_connected_reader(self):
        control_sock, provider_sock = socket.socketpair()
        client = ProviderPersistentClient(
            connector=lambda: provider_sock,
            handshake=lambda sock, challenge: ready_session(),
            request_handler=lambda message_type, payload, session: {},
            min_backoff_seconds=0.01,
            max_backoff_seconds=0.01,
        )
        thread = threading.Thread(target=client.serve_forever)
        thread.start()
        send_frame(control_sock, {
            "kind": "challenge",
            "session_id": "session-a",
            "challenge": "challenge",
            "control_plane_id": "cp-1",
        })
        # The handshake callback is enough for the provider loop to enter its
        # blocking frame reader; no request is needed for this lifecycle test.
        for _ in range(100):
            with client._socket_lock:
                connected = client._active_socket is not None
            if connected:
                break
            time.sleep(0.01)
        self.assertTrue(connected)
        client.stop()
        thread.join(2)
        self.assertFalse(thread.is_alive())
        control_sock.close()
        provider_sock.close()

    def test_correlated_request_response_over_one_persistent_socket(self):
        server_sock, provider_sock = socket.socketpair()
        connection = PersistentNodeConnection(sock=server_sock, session=ready_session(), control_plane_id="cp-1")
        client = PersistentNodeControlClient()
        client.register(connection)

        def provider():
            frame = recv_frame(provider_sock)
            self.assertEqual(frame["kind"], "request")
            self.assertEqual(frame["message_type"], "ExecutionAttestationRequest")
            self.assertEqual(frame["session_id"], "session-a")
            send_frame(provider_sock, {
                "kind": "response",
                "correlation_id": frame["request_id"],
                "ok": True,
                "payload": {"session_id": "session-a", "node_id": "node-a", "attestation": {"node_id": "node-a"}},
            })

        thread = threading.Thread(target=provider)
        thread.start()
        result = client.request(
            node_id="node-a",
            message_type="ExecutionAttestationRequest",
            payload={"request": {"job_id": "job-1"}},
            timeout_seconds=2,
        )
        thread.join(2)
        self.assertEqual(result["node_id"], "node-a")
        connection.close()
        provider_sock.close()

    def test_heartbeat_keeps_connection_live_then_evicts_closed_peer(self):
        server_sock, provider_sock = socket.socketpair()
        connection = PersistentNodeConnection(sock=server_sock, session=ready_session(), control_plane_id="cp-1")
        client = PersistentNodeControlClient()
        client.register(connection)

        def provider():
            frame = recv_frame(provider_sock)
            self.assertEqual(frame["kind"], "ping")
            send_frame(provider_sock, {"kind": "pong", "sent_at": frame["sent_at"]})

        thread = threading.Thread(target=provider)
        thread.start()
        self.assertEqual(client.heartbeat_once(stale_after_seconds=60), ())
        thread.join(2)
        time.sleep(0.02)
        self.assertTrue(connection.alive)
        provider_sock.close()
        for _ in range(50):
            if not connection.alive:
                break
            time.sleep(0.01)
        with self.assertRaises(ChannelClosed):
            client.request(node_id="node-a", message_type="x", payload={}, timeout_seconds=0.1)

    def test_replacing_same_node_connection_closes_old_channel(self):
        a_server, a_provider = socket.socketpair()
        b_server, b_provider = socket.socketpair()
        client = PersistentNodeControlClient()
        first = PersistentNodeConnection(sock=a_server, session=ready_session(), control_plane_id="cp-1")
        second = PersistentNodeConnection(sock=b_server, session=ready_session(), control_plane_id="cp-1")
        client.register(first)
        client.register(second)
        self.assertFalse(first.alive)
        self.assertTrue(second.alive)
        second.close()
        a_provider.close()
        b_provider.close()

    def test_revoke_session_fan_out(self):
        server_sock, provider_sock = socket.socketpair()
        session = ready_session("node-revoked")
        connection = PersistentNodeConnection(sock=server_sock, session=session, control_plane_id="cp-1")
        client = PersistentNodeControlClient()
        client.register(connection)
        self.assertTrue(client.is_connected("node-revoked"))

        # Revoke via event
        client.handle_revocation_event("node", "node-revoked")
        self.assertFalse(client.is_connected("node-revoked"))
        self.assertFalse(connection.alive)
        provider_sock.close()

    def test_revoke_all_sessions(self):
        s1, p1 = socket.socketpair()
        s2, p2 = socket.socketpair()
        client = PersistentNodeControlClient()
        c1 = PersistentNodeConnection(sock=s1, session=ready_session("node-1"), control_plane_id="cp-1")
        c2 = PersistentNodeConnection(sock=s2, session=ready_session("node-2"), control_plane_id="cp-1")
        client.register(c1)
        client.register(c2)
        self.assertEqual(len(client.live_node_ids()), 2)

        revoked = client.revoke_all()
        self.assertEqual(sorted(revoked), ["node-1", "node-2"])
        self.assertEqual(client.live_node_ids(), ())
        self.assertFalse(c1.alive)
        self.assertFalse(c2.alive)
        p1.close()
        p2.close()

    def test_provider_client_stream_handler_sends_ordered_terminal_chunks(self):
        control_sock, provider_sock = socket.socketpair()
        client = ProviderPersistentClient(
            connector=lambda: provider_sock,
            handshake=lambda sock, challenge: ready_session(),
            request_handler=lambda message_type, payload, session: {},
            stream_handler=lambda message_type, payload, session: iter((
                {"delta": "a", "done": False},
                {"delta": "b", "done": True},
            )),
            min_backoff_seconds=0.01,
            max_backoff_seconds=0.01,
        )
        thread = threading.Thread(target=client.serve_forever)
        thread.start()
        send_frame(control_sock, {
            "kind": "challenge",
            "session_id": "session-a",
            "challenge": "challenge",
            "control_plane_id": "cp-1",
        })
        send_frame(control_sock, {
            "kind": "request",
            "request_id": "stream-1",
            "message_type": "InferenceRequest",
            "payload": {"stream": True},
            "session_id": "session-a",
            "session_revision": 5,
        })
        first = recv_frame(control_sock)
        second = recv_frame(control_sock)
        self.assertEqual([first["kind"], second["kind"]], ["stream", "stream"])
        self.assertFalse(first["done"])
        self.assertTrue(second["done"])
        self.assertEqual([first["payload"]["delta"], second["payload"]["delta"]], ["a", "b"])
        client.stop()
        control_sock.close()
        provider_sock.close()
        thread.join(2)


if __name__ == "__main__":
    unittest.main()
