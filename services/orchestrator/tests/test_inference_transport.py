from __future__ import annotations

import socket
import threading
import unittest
from datetime import datetime, timedelta, timezone

from protocol.node_session import NodeSessionState, SessionSnapshot
from services.orchestrator.inference_transport import (
    AuthenticatedNodeInferenceClient,
    InferenceTransportError,
    make_inference_request_handler,
)
from services.orchestrator.persistent_control_channel import (
    PersistentNodeConnection,
    PersistentNodeControlClient,
    recv_frame,
    send_frame,
)


def ready_session() -> SessionSnapshot:
    return SessionSnapshot(
        session_id="session-a",
        state=NodeSessionState.READY,
        revision=5,
        protocol_major=0,
        protocol_minor=2,
        node_id="node-a",
        principal_id="provider-a",
        auth_method="computemesh-ed25519-v1",
        credential_expires_at=datetime.now(timezone.utc) + timedelta(minutes=10),
        negotiated_capabilities=frozenset({"execution_attestation_v1", "inference_v1", "inference_stream_v1"}),
        profile_revision=3,
        drain_reason=None,
        close_reason=None,
    )


class InferenceTransportTests(unittest.TestCase):
    def test_request_cancel_event_signals_live_control_channel(self):
        class BlockingControlClient:
            def __init__(self) -> None:
                self.started = threading.Event()
                self.cancelled = threading.Event()
                self.cancel_calls: list[tuple[str, str, str]] = []

            def session_for(self, _node_id: str) -> SessionSnapshot:
                return ready_session()

            def cancel(self, *, node_id: str, request_id: str, reason: str) -> bool:
                self.cancel_calls.append((node_id, request_id, reason))
                self.cancelled.set()
                return True

            def request(self, **_kwargs):
                self.started.set()
                if not self.cancelled.wait(1):
                    raise AssertionError("cancel was not delivered")
                raise RuntimeError("request cancelled")

        control = BlockingControlClient()
        cancel_event = threading.Event()
        result: list[BaseException] = []
        inference = AuthenticatedNodeInferenceClient(control, timeout_seconds=2)

        def run() -> None:
            try:
                inference.request(
                    node_id="node-a", session_id="session-a", turn_id="turn-cancel",
                    lease_id="lease-a", model_id="model-a",
                    messages=[{"role": "user", "content": "hello"}], max_tokens=8,
                    cancel_event=cancel_event,
                )
            except BaseException as exc:
                result.append(exc)

        thread = threading.Thread(target=run)
        thread.start()
        self.assertTrue(control.started.wait(1))
        cancel_event.set()
        thread.join(2)
        self.assertFalse(thread.is_alive())
        self.assertTrue(control.cancelled.is_set())
        self.assertEqual(len(control.cancel_calls), 1)
        self.assertEqual(control.cancel_calls[0][0], "node-a")
        self.assertEqual(control.cancel_calls[0][2], "agent_turn_cancelled")
        self.assertEqual(len(result), 1)

    def test_request_binds_provider_capacity_and_releases_it(self):
        class CapacityClient:
            def __init__(self) -> None:
                self.reserves: list[dict[str, object]] = []
                self.releases: list[dict[str, object]] = []

            def reserve_capacity(self, **kwargs):
                self.reserves.append(dict(kwargs))
                return {
                    "node_id": kwargs["node_id"],
                    "job_id": kwargs["job_id"],
                    "lease_id": kwargs["lease_id"],
                }

            def release_capacity(self, **kwargs):
                self.releases.append(dict(kwargs))
                return True

        class ControlClient:
            def session_for(self, _node_id: str) -> SessionSnapshot:
                return ready_session()

            def request(self, **_kwargs):
                return {
                    "schema_version": 1,
                    "session_id": "session-a",
                    "turn_id": "turn-capacity",
                    "lease_id": "lease-capacity",
                    "node_id": "node-a",
                    "model_id": "model-a",
                    "output": "done",
                }

        capacity = CapacityClient()
        result = AuthenticatedNodeInferenceClient(
            ControlClient(), capacity_client=capacity, capacity_memory_mb=2048
        ).request(
            node_id="node-a",
            session_id="session-a",
            turn_id="turn-capacity",
            lease_id="lease-capacity",
            model_id="model-a",
            messages=[{"role": "user", "content": "hello"}],
            max_tokens=8,
        )
        self.assertEqual(result["output"], "done")
        self.assertEqual(len(capacity.reserves), 1)
        self.assertEqual(capacity.reserves[0]["memory_mb"], 2048)
        self.assertEqual(len(capacity.releases), 1)
        self.assertEqual(capacity.releases[0]["lease_id"], "lease-capacity")

    def test_request_is_bound_and_validated_over_persistent_channel(self):
        server_sock, provider_sock = socket.socketpair()
        connection = PersistentNodeConnection(sock=server_sock, session=ready_session(), control_plane_id="cp-1")
        client = PersistentNodeControlClient()
        client.register(connection)

        def provider() -> None:
            frame = recv_frame(provider_sock)
            self.assertEqual(frame["message_type"], "InferenceRequest")
            self.assertEqual(frame["session_id"], "session-a")
            self.assertEqual(frame["payload"]["lease_id"], "lease-a")
            self.assertEqual(frame["payload"]["model_id"], "model-a")
            self.assertEqual(frame["payload"]["tools"][0]["function"]["name"], "read_status")
            send_frame(provider_sock, {
                "kind": "response",
                "correlation_id": frame["request_id"],
                "ok": True,
                "payload": {
                    "schema_version": 1,
                    "session_id": "session-a",
                    "turn_id": "turn-a",
                    "lease_id": "lease-a",
                    "node_id": "node-a",
                    "model_id": "model-a",
                    "output": "done",
                },
            })

        thread = threading.Thread(target=provider)
        thread.start()
        result = AuthenticatedNodeInferenceClient(client, timeout_seconds=2).request(
            node_id="node-a",
            session_id="session-a",
            turn_id="turn-a",
            lease_id="lease-a",
            model_id="model-a",
            messages=[{"role": "user", "content": "hello"}],
            max_tokens=32,
            tools=[{"type": "function", "function": {"name": "read_status"}}],
        )
        thread.join(2)
        self.assertEqual(result["output"], "done")
        connection.close()
        provider_sock.close()

    def test_missing_capability_fails_before_wire_request(self):
        server_sock, provider_sock = socket.socketpair()
        session = ready_session()
        session = SessionSnapshot(**{**session.__dict__, "negotiated_capabilities": frozenset({"execution_attestation_v1"})})
        connection = PersistentNodeConnection(sock=server_sock, session=session, control_plane_id="cp-1")
        client = PersistentNodeControlClient()
        client.register(connection)
        with self.assertRaises(InferenceTransportError):
            AuthenticatedNodeInferenceClient(client).request(
                node_id="node-a", session_id="session-a", turn_id="turn-a", lease_id="lease-a",
                model_id="model-a", messages=[{"role": "user", "content": "hello"}], max_tokens=1,
            )
        connection.close()
        provider_sock.close()

    def test_provider_handler_checks_session_and_response_bindings(self):
        seen: list[str] = []

        def executor(session: SessionSnapshot, request: dict[str, object]) -> dict[str, object]:
            seen.append(str(request["model_id"]))
            return {
                "schema_version": 1,
                "session_id": session.session_id,
                "turn_id": request["turn_id"],
                "lease_id": request["lease_id"],
                "node_id": session.node_id,
                "model_id": request["model_id"],
                "output": "ok",
            }

        handler = make_inference_request_handler(executor)
        result = handler("InferenceRequest", {
            "schema_version": 1,
            "session_id": "session-a",
            "turn_id": "turn-a",
            "lease_id": "lease-a",
            "model_id": "model-a",
            "messages": [{"role": "user", "content": "hello"}],
            "max_tokens": 16,
            "stream": False,
        }, ready_session())
        self.assertEqual(result["output"], "ok")
        self.assertEqual(seen, ["model-a"])

    def test_provider_handler_rejects_session_mismatch(self):
        handler = make_inference_request_handler(lambda session, request: {})
        with self.assertRaises(InferenceTransportError):
            handler("InferenceRequest", {
                "schema_version": 1,
                "session_id": "other-session",
                "turn_id": "turn-a",
                "lease_id": "lease-a",
                "model_id": "model-a",
                "messages": [{"role": "user", "content": "hello"}],
                "max_tokens": 16,
                "stream": False,
            }, ready_session())

    def test_streaming_request_delivers_bound_chunks_and_final_marker(self):
        server_sock, provider_sock = socket.socketpair()
        connection = PersistentNodeConnection(sock=server_sock, session=ready_session(), control_plane_id="cp-1")
        client = PersistentNodeControlClient()
        client.register(connection)

        def provider() -> None:
            frame = recv_frame(provider_sock)
            self.assertEqual(frame["message_type"], "InferenceRequest")
            self.assertTrue(frame["payload"]["stream"])
            base = {
                "schema_version": 1,
                "session_id": "session-a",
                "turn_id": "turn-stream",
                "lease_id": "lease-stream",
                "node_id": "node-a",
                "model_id": "model-a",
                "finish_reason": None,
            }
            send_frame(provider_sock, {
                "kind": "stream", "correlation_id": frame["request_id"], "ok": True, "done": False,
                "payload": {**base, "delta": "hel", "done": False},
            })
            send_frame(provider_sock, {
                "kind": "stream", "correlation_id": frame["request_id"], "ok": True, "done": True,
                "payload": {**base, "delta": "lo", "done": True, "finish_reason": "stop"},
            })

        thread = threading.Thread(target=provider)
        thread.start()
        events: list[tuple[str, dict[str, object]]] = []
        chunks = list(AuthenticatedNodeInferenceClient(
            client,
            timeout_seconds=2,
            event_sink=lambda event_type, payload: events.append((event_type, dict(payload))),
        ).stream(
            node_id="node-a", session_id="session-a", turn_id="turn-stream", lease_id="lease-stream",
            model_id="model-a", messages=[{"role": "user", "content": "hello"}], max_tokens=32,
        ))
        thread.join(2)
        self.assertEqual([chunk["delta"] for chunk in chunks], ["hel", "lo"])
        self.assertTrue(chunks[-1]["done"])
        self.assertEqual(
            [event_type for event_type, _ in events],
            [
                "mesh.inference.stream.started",
                "mesh.inference.stream.chunk",
                "mesh.inference.stream.chunk",
                "mesh.inference.stream.completed",
            ],
        )
        self.assertNotIn("delta", events[1][1])
        self.assertEqual(events[-1][1]["output_digest"], __import__("hashlib").sha256(b"hello").hexdigest())
        connection.close()
        provider_sock.close()

    def test_streaming_requires_stream_capability(self):
        server_sock, provider_sock = socket.socketpair()
        session = ready_session()
        session = SessionSnapshot(**{**session.__dict__, "negotiated_capabilities": frozenset({"inference_v1"})})
        connection = PersistentNodeConnection(sock=server_sock, session=session, control_plane_id="cp-1")
        client = PersistentNodeControlClient()
        client.register(connection)
        with self.assertRaises(InferenceTransportError):
            AuthenticatedNodeInferenceClient(client).stream(
                node_id="node-a", session_id="session-a", turn_id="turn-a", lease_id="lease-a",
                model_id="model-a", messages=[{"role": "user", "content": "hello"}], max_tokens=1,
            )
        connection.close()
        provider_sock.close()


if __name__ == "__main__":
    unittest.main()
