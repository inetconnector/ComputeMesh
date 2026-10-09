"""Persistent provider <-> control-plane channel for live ComputeMesh sessions.

The channel deliberately separates transport confidentiality from node identity.
TLS is used for server authentication/encryption when configured; provider identity
is established by the existing ComputeMesh Ed25519 challenge proof and NodeSession
state machine. One long-lived connection carries heartbeats and control requests.
"""
from __future__ import annotations

import inspect
import json
import queue
import socket
import ssl
import struct
import threading
import time
from dataclasses import dataclass
from typing import Any, Callable, Iterator, Mapping

from protocol.control import parse_control_envelope
from protocol.node_identity import AUTH_METHOD, Ed25519ChallengeVerifier
from protocol.node_session import NodeSession, SessionSnapshot
from protocol.session_wire import BenchmarkAcceptancePolicy, NodeSessionWireHandler

MAX_FRAME_BYTES = 2 * 1024 * 1024


class PersistentControlChannelError(RuntimeError):
    pass


class ChannelClosed(PersistentControlChannelError):
    pass


class RequestTimeout(PersistentControlChannelError):
    pass


class RequestCancelled(PersistentControlChannelError):
    """Raised when an in-flight provider request is cancelled explicitly."""


def _validate_request_id(value: str) -> str:
    clean = str(value or "").strip()
    if not 1 <= len(clean) <= 160 or any(character.isspace() for character in clean):
        raise ValueError("request_id must be a bounded non-whitespace string")
    return clean


def _recv_exact(sock: socket.socket, size: int) -> bytes:
    chunks: list[bytes] = []
    remaining = size
    while remaining:
        data = sock.recv(remaining)
        if not data:
            raise ChannelClosed("control channel closed")
        chunks.append(data)
        remaining -= len(data)
    return b"".join(chunks)


def send_frame(sock: socket.socket, document: Mapping[str, Any], *, lock: threading.Lock | None = None) -> None:
    raw = json.dumps(document, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    if not raw or len(raw) > MAX_FRAME_BYTES:
        raise PersistentControlChannelError("control frame exceeds size limit")
    packet = struct.pack(">I", len(raw)) + raw
    if lock is None:
        sock.sendall(packet)
    else:
        with lock:
            sock.sendall(packet)


def recv_frame(sock: socket.socket) -> dict[str, Any]:
    size = struct.unpack(">I", _recv_exact(sock, 4))[0]
    if size <= 0 or size > MAX_FRAME_BYTES:
        raise PersistentControlChannelError("invalid control frame length")
    try:
        value = json.loads(_recv_exact(sock, size).decode("utf-8"))
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise PersistentControlChannelError("control frame is not UTF-8 JSON") from exc
    if not isinstance(value, dict):
        raise PersistentControlChannelError("control frame root must be an object")
    return value


@dataclass
class _Pending:
    event: threading.Event
    response: dict[str, Any] | None = None
    error: Exception | None = None
    stream_queue: queue.Queue[tuple[str, dict[str, Any] | Exception | None]] | None = None


class PersistentNodeConnection:
    """Server-side long-lived connection bound to one authenticated NodeSession."""

    def __init__(self, *, sock: socket.socket, session: SessionSnapshot, control_plane_id: str):
        if not session.node_id:
            raise ValueError("persistent connection requires authenticated node identity")
        self.sock = sock
        self.session = session
        self.control_plane_id = control_plane_id
        self.node_id = session.node_id
        self._write_lock = threading.Lock()
        self._pending_lock = threading.Lock()
        self._pending: dict[str, _Pending] = {}
        self._closed = threading.Event()
        self._last_pong = time.monotonic()
        self._reader = threading.Thread(target=self._read_loop, name=f"cm-control-{self.node_id}", daemon=True)
        self._reader.start()

    @property
    def alive(self) -> bool:
        return not self._closed.is_set()

    @property
    def last_pong_monotonic(self) -> float:
        return self._last_pong

    def close(self) -> None:
        if self._closed.is_set():
            return
        self._closed.set()
        try:
            self.sock.shutdown(socket.SHUT_RDWR)
        except OSError:
            pass
        try:
            self.sock.close()
        except OSError:
            pass
        with self._pending_lock:
            pending = list(self._pending.values())
            self._pending.clear()
        for item in pending:
            item.error = ChannelClosed(f"node {self.node_id} disconnected")
            item.event.set()
            if item.stream_queue is not None:
                item.stream_queue.put(("error", item.error))

    def _read_loop(self) -> None:
        try:
            while not self._closed.is_set():
                frame = recv_frame(self.sock)
                kind = frame.get("kind")
                if kind == "pong":
                    self._last_pong = time.monotonic()
                    continue
                if kind not in {"response", "stream"}:
                    raise PersistentControlChannelError("unexpected provider frame")
                correlation_id = frame.get("correlation_id")
                if not isinstance(correlation_id, str):
                    raise PersistentControlChannelError("response lacks correlation_id")
                with self._pending_lock:
                    pending = self._pending.get(correlation_id)
                if pending is None:
                    continue
                if kind == "stream":
                    stream_queue = pending.stream_queue
                    if stream_queue is None:
                        pending.error = PersistentControlChannelError("received stream data for a non-stream request")
                        with self._pending_lock:
                            self._pending.pop(correlation_id, None)
                        pending.event.set()
                        continue
                    if frame.get("ok") is not True or not isinstance(frame.get("payload"), dict):
                        error = PersistentControlChannelError(str(frame.get("error") or "provider stream failed")[:512])
                        stream_queue.put(("error", error))
                        stream_queue.put(("done", None))
                        with self._pending_lock:
                            self._pending.pop(correlation_id, None)
                        continue
                    stream_queue.put(("item", dict(frame["payload"])))
                    if frame.get("done") is True:
                        stream_queue.put(("done", None))
                        with self._pending_lock:
                            self._pending.pop(correlation_id, None)
                    continue
                with self._pending_lock:
                    self._pending.pop(correlation_id, None)
                if pending.stream_queue is not None:
                    error = PersistentControlChannelError(
                        str(frame.get("error") or "provider stream ended without stream frame")[:512]
                    )
                    pending.stream_queue.put(("error", error))
                    pending.stream_queue.put(("done", None))
                    pending.event.set()
                    continue
                if frame.get("ok") is True and isinstance(frame.get("payload"), dict):
                    pending.response = dict(frame["payload"])
                else:
                    pending.error = PersistentControlChannelError(str(frame.get("error") or "provider request failed")[:512])
                pending.event.set()
        except Exception:
            self.close()

    def ping(self) -> None:
        send_frame(self.sock, {"kind": "ping", "sent_at": int(time.time())}, lock=self._write_lock)

    def request(
        self,
        *,
        message_type: str,
        payload: dict[str, Any],
        timeout_seconds: float,
        request_id: str | None = None,
    ) -> dict[str, Any]:
        if not self.alive:
            raise ChannelClosed(f"node {self.node_id} control channel is closed")
        if timeout_seconds <= 0 or timeout_seconds > 300:
            raise ValueError("timeout_seconds must be within (0,300]")
        request_id = _validate_request_id(request_id) if request_id is not None else f"cp-{time.time_ns():x}-{threading.get_ident():x}"
        pending = _Pending(threading.Event())
        with self._pending_lock:
            self._pending[request_id] = pending
        try:
            send_frame(
                self.sock,
                {
                    "kind": "request",
                    "request_id": request_id,
                    "message_type": message_type,
                    "payload": payload,
                    "session_id": self.session.session_id,
                    "session_revision": self.session.revision,
                },
                lock=self._write_lock,
            )
        except Exception:
            with self._pending_lock:
                self._pending.pop(request_id, None)
            raise
        if not pending.event.wait(timeout_seconds):
            with self._pending_lock:
                self._pending.pop(request_id, None)
            raise RequestTimeout(f"node {self.node_id} did not answer {message_type}")
        if pending.error is not None:
            raise pending.error
        assert pending.response is not None
        return pending.response

    def cancel(self, request_id: str, *, reason: str = "cancelled") -> bool:
        """Cancel one pending request and notify the provider cooperatively."""
        request_id = _validate_request_id(request_id)
        reason = str(reason or "cancelled")[:256]
        if not reason:
            reason = "cancelled"
        with self._pending_lock:
            pending = self._pending.pop(request_id, None)
        if pending is None:
            return False
        try:
            send_frame(
                self.sock,
                {"kind": "cancel", "request_id": request_id, "reason": reason},
                lock=self._write_lock,
            )
        except Exception:
            self.close()
        pending.error = RequestCancelled(f"request {request_id} was cancelled")
        pending.event.set()
        if pending.stream_queue is not None:
            pending.stream_queue.put(("error", pending.error))
            pending.stream_queue.put(("done", None))
        return True

    def request_stream(
        self,
        *,
        message_type: str,
        payload: dict[str, Any],
        timeout_seconds: float,
        request_id: str | None = None,
    ) -> Iterator[dict[str, Any]]:
        if not self.alive:
            raise ChannelClosed(f"node {self.node_id} control channel is closed")
        if timeout_seconds <= 0 or timeout_seconds > 300:
            raise ValueError("timeout_seconds must be within (0,300]")
        request_id = _validate_request_id(request_id) if request_id is not None else f"cp-stream-{time.time_ns():x}-{threading.get_ident():x}"
        stream_queue: queue.Queue[tuple[str, dict[str, Any] | Exception | None]] = queue.Queue()
        pending = _Pending(threading.Event(), stream_queue=stream_queue)
        with self._pending_lock:
            self._pending[request_id] = pending
        try:
            send_frame(
                self.sock,
                {
                    "kind": "request",
                    "request_id": request_id,
                    "message_type": message_type,
                    "payload": payload,
                    "session_id": self.session.session_id,
                    "session_revision": self.session.revision,
                },
                lock=self._write_lock,
            )
        except Exception:
            with self._pending_lock:
                self._pending.pop(request_id, None)
            raise
        deadline = time.monotonic() + timeout_seconds

        def receive() -> Iterator[dict[str, Any]]:
            try:
                while True:
                    remaining = deadline - time.monotonic()
                    if remaining <= 0:
                        with self._pending_lock:
                            self._pending.pop(request_id, None)
                        raise RequestTimeout(f"node {self.node_id} did not finish {message_type}")
                    try:
                        kind, value = stream_queue.get(timeout=remaining)
                    except queue.Empty as exc:
                        with self._pending_lock:
                            self._pending.pop(request_id, None)
                        raise RequestTimeout(f"node {self.node_id} did not finish {message_type}") from exc
                    if kind == "error":
                        if isinstance(value, Exception):
                            raise value
                        raise PersistentControlChannelError("provider stream failed")
                    if kind == "done":
                        return
                    if not isinstance(value, dict):
                        raise PersistentControlChannelError("provider stream chunk is not an object")
                    yield value
            finally:
                with self._pending_lock:
                    self._pending.pop(request_id, None)

        return receive()


class PersistentNodeControlClient:
    """Thread-safe NodeControlClient backed by current persistent connections."""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._connections: dict[str, PersistentNodeConnection] = {}

    def register(self, connection: PersistentNodeConnection) -> None:
        with self._lock:
            old = self._connections.get(connection.node_id)
            self._connections[connection.node_id] = connection
        if old is not None and old is not connection:
            old.close()

    def unregister(self, node_id: str, connection: PersistentNodeConnection | None = None) -> None:
        with self._lock:
            current = self._connections.get(node_id)
            if current is None or (connection is not None and current is not connection):
                return
            self._connections.pop(node_id, None)
        current.close()

    def is_connected(self, node_id: str) -> bool:
        """Return true only for the currently registered live connection."""
        with self._lock:
            connection = self._connections.get(node_id)
            return connection is not None and connection.alive

    def session_for(self, node_id: str) -> SessionSnapshot:
        """Return the authenticated snapshot for a currently live node channel."""
        with self._lock:
            connection = self._connections.get(node_id)
        if connection is None or not connection.alive:
            raise ChannelClosed(f"node {node_id} has no live persistent control channel")
        return connection.session

    def live_node_ids(self) -> tuple[str, ...]:
        with self._lock:
            return tuple(sorted(node_id for node_id, connection in self._connections.items() if connection.alive))

    def request(
        self,
        *,
        node_id: str,
        message_type: str,
        payload: dict[str, Any],
        timeout_seconds: float,
        request_id: str | None = None,
    ) -> dict[str, Any]:
        with self._lock:
            connection = self._connections.get(node_id)
        if connection is None or not connection.alive:
            raise ChannelClosed(f"node {node_id} has no live persistent control channel")
        return connection.request(
            message_type=message_type,
            payload=payload,
            timeout_seconds=timeout_seconds,
            request_id=request_id,
        )

    def cancel(self, *, node_id: str, request_id: str, reason: str = "cancelled") -> bool:
        """Cancel a request on the currently authenticated node channel."""
        with self._lock:
            connection = self._connections.get(node_id)
        if connection is None or not connection.alive:
            raise ChannelClosed(f"node {node_id} has no live persistent control channel")
        return connection.cancel(request_id, reason=reason)

    def request_stream(
        self,
        *,
        node_id: str,
        message_type: str,
        payload: dict[str, Any],
        timeout_seconds: float,
        request_id: str | None = None,
    ) -> Iterator[dict[str, Any]]:
        with self._lock:
            connection = self._connections.get(node_id)
        if connection is None or not connection.alive:
            raise ChannelClosed(f"node {node_id} has no live persistent control channel")
        return connection.request_stream(
            message_type=message_type,
            payload=payload,
            timeout_seconds=timeout_seconds,
            request_id=request_id,
        )

    def reserve_capacity(
        self,
        *,
        node_id: str,
        job_id: str,
        lease_id: str,
        ttl_seconds: int,
        device_id: str = "default",
        memory_mb: int = 0,
        timeout_seconds: float = 15.0,
    ) -> dict[str, Any]:
        """Reserve provider-local capacity for one authenticated inference lease."""
        session = self.session_for(node_id)
        if "capacity_reservation_v1" not in session.negotiated_capabilities:
            raise PersistentControlChannelError("node lacks capacity_reservation_v1")
        response = self.request(
            node_id=node_id,
            message_type="CapacityReserveRequest",
            payload={
                "job_id": str(job_id),
                "lease_id": str(lease_id),
                "ttl_seconds": int(ttl_seconds),
                "device_id": str(device_id),
                "memory_mb": int(memory_mb),
            },
            timeout_seconds=float(timeout_seconds),
        )
        if (
            response.get("node_id") != node_id
            or response.get("job_id") != str(job_id)
            or response.get("lease_id") != str(lease_id)
        ):
            raise PersistentControlChannelError("provider capacity reservation binding mismatch")
        return response

    def release_capacity(
        self,
        *,
        node_id: str,
        job_id: str,
        lease_id: str,
        timeout_seconds: float = 15.0,
    ) -> bool:
        """Release one provider-local capacity reservation idempotently."""
        session = self.session_for(node_id)
        if "capacity_reservation_v1" not in session.negotiated_capabilities:
            raise PersistentControlChannelError("node lacks capacity_reservation_v1")
        response = self.request(
            node_id=node_id,
            message_type="CapacityReleaseRequest",
            payload={"job_id": str(job_id), "lease_id": str(lease_id)},
            timeout_seconds=float(timeout_seconds),
        )
        if response.get("node_id") != node_id or response.get("job_id") != str(job_id):
            raise PersistentControlChannelError("provider capacity release binding mismatch")
        return bool(response.get("released", False))

    def heartbeat_once(self, *, stale_after_seconds: float = 45.0) -> tuple[str, ...]:
        now = time.monotonic()
        stale: list[str] = []
        with self._lock:
            items = list(self._connections.items())
        for node_id, connection in items:
            if not connection.alive or now - connection.last_pong_monotonic > stale_after_seconds:
                stale.append(node_id)
                self.unregister(node_id, connection)
                continue
            try:
                connection.ping()
            except Exception:
                stale.append(node_id)
                self.unregister(node_id, connection)
        return tuple(stale)

    def revoke_session(self, node_id: str, reason: str = "credential_revoked") -> bool:
        """Immediately terminate and unregister an active node session upon revocation."""
        with self._lock:
            connection = self._connections.pop(node_id, None)
        if connection is not None:
            connection.close()
            return True
        return False

    def revoke_all(self, reason: str = "cluster_shutdown") -> tuple[str, ...]:
        """Terminate all active node sessions immediately."""
        with self._lock:
            items = list(self._connections.items())
            self._connections.clear()
        for _, connection in items:
            connection.close()
        return tuple(node_id for node_id, _ in items)

    def handle_revocation_event(self, target_type: str, target_id: str) -> None:
        """Handle revocation callback from IdentityStore: fan out session termination."""
        if target_type == "node":
            self.revoke_session(target_id, reason="node_identity_revoked")
        elif target_type == "key":
            # Check all live connections
            with self._lock:
                matching_nodes = [
                    node_id
                    for node_id, conn in self._connections.items()
                    if getattr(conn.session, "key_id", None) == target_id
                ]
            for node_id in matching_nodes:
                self.revoke_session(node_id, reason="node_key_revoked")



@dataclass(frozen=True)
class AcceptedProviderSession:
    session: SessionSnapshot
    connection: PersistentNodeConnection


def accept_authenticated_provider(
    *,
    sock: socket.socket,
    verifier: Ed25519ChallengeVerifier,
    benchmark_policy: BenchmarkAcceptancePolicy,
    control_client: PersistentNodeControlClient,
    control_plane_id: str,
    control_plane_capabilities: tuple[str, ...],
    required_capabilities: tuple[str, ...] = ("execution_attestation_v1",),
    handshake_timeout_seconds: float = 15.0,
) -> AcceptedProviderSession:
    """Authenticate a newly accepted socket using the existing NodeSession wire semantics."""
    sock.settimeout(handshake_timeout_seconds)
    session = NodeSession.create(f"session-{time.time_ns():x}")
    handler = NodeSessionWireHandler(
        session=session,
        verifier=verifier,
        benchmark_policy=benchmark_policy,
        control_plane_capabilities=control_plane_capabilities,
        required_capabilities=required_capabilities,
    )
    send_frame(sock, {"kind": "challenge", "session_id": session.session_id, "challenge": session.challenge, "control_plane_id": control_plane_id})
    # Handshake messages are normal validated ControlEnvelopes: Hello -> Auth -> Capabilities.
    for expected in ("NodeHello", "NodeAuthenticate", "CapabilityNegotiation"):
        frame = recv_frame(sock)
        if frame.get("kind") != "envelope" or not isinstance(frame.get("document"), dict):
            raise PersistentControlChannelError("handshake requires control envelope frames")
        envelope = parse_control_envelope(frame["document"])
        if envelope.message_type != expected:
            raise PersistentControlChannelError(f"expected {expected}, got {envelope.message_type}")
        snapshot = handler.handle(envelope)
        send_frame(sock, {"kind": "session_ack", "state": snapshot.state.value, "revision": snapshot.revision})
    snapshot = session.snapshot()
    if snapshot.auth_method != AUTH_METHOD or not snapshot.node_id:
        raise PersistentControlChannelError("provider session did not establish Ed25519 identity")
    sock.settimeout(None)
    connection = PersistentNodeConnection(sock=sock, session=snapshot, control_plane_id=control_plane_id)
    control_client.register(connection)
    return AcceptedProviderSession(snapshot, connection)


class ProviderPersistentClient:
    """Provider-side reconnecting channel after an authenticated session handshake.

    `handshake` must perform NodeHello/NodeAuthenticate/CapabilityNegotiation using
    the server challenge and return the resulting SessionSnapshot. `request_handler`
    executes control-plane requests locally (for example execution attestations).
    """

    def __init__(
        self,
        *,
        connector: Callable[[], socket.socket],
        handshake: Callable[[socket.socket, dict[str, Any]], SessionSnapshot],
        request_handler: Callable[[str, dict[str, Any], SessionSnapshot], dict[str, Any]],
        stream_handler: Callable[[str, dict[str, Any], SessionSnapshot], Iterator[Mapping[str, Any]]] | None = None,
        min_backoff_seconds: float = 1.0,
        max_backoff_seconds: float = 30.0,
    ) -> None:
        self.connector = connector
        self.handshake = handshake
        self.request_handler = request_handler
        self.stream_handler = stream_handler
        self.min_backoff_seconds = min_backoff_seconds
        self.max_backoff_seconds = max_backoff_seconds
        self._stop = threading.Event()
        self._socket_lock = threading.Lock()
        self._active_socket: socket.socket | None = None
        self._request_handler_accepts_cancel = self._supports_cancel(request_handler)
        self._stream_handler_accepts_cancel = self._supports_cancel(stream_handler) if stream_handler is not None else False

    @staticmethod
    def _supports_cancel(handler: Callable[..., Any] | None) -> bool:
        if handler is None:
            return False
        try:
            parameters = inspect.signature(handler).parameters.values()
        except (TypeError, ValueError):
            return False
        positional = [
            parameter for parameter in parameters
            if parameter.kind in {inspect.Parameter.POSITIONAL_ONLY, inspect.Parameter.POSITIONAL_OR_KEYWORD}
        ]
        return len(positional) >= 4 or any(
            parameter.kind is inspect.Parameter.VAR_POSITIONAL
            for parameter in parameters
        )

    def _dispatch_request(
        self,
        *,
        sock: socket.socket,
        frame: Mapping[str, Any],
        session: SessionSnapshot,
        write_lock: threading.Lock,
        cancel_event: threading.Event,
        active: dict[str, threading.Event],
        active_lock: threading.Lock,
    ) -> None:
        request_id = str(frame["request_id"])
        try:
            if frame.get("session_id") != session.session_id or frame.get("session_revision") != session.revision:
                raise PersistentControlChannelError("request is bound to another session revision")
            message_type = str(frame.get("message_type"))
            payload = dict(frame.get("payload") or {})
            if payload.get("stream") is True:
                if self.stream_handler is None:
                    raise PersistentControlChannelError("streaming is not enabled on this provider")
                if self._stream_handler_accepts_cancel:
                    chunks = self.stream_handler(message_type, payload, session, cancel_event)  # type: ignore[misc]
                else:
                    chunks = self.stream_handler(message_type, payload, session)
                sent_chunk = False
                sent_done = False
                for chunk in chunks:
                    if cancel_event.is_set():
                        raise RequestCancelled(f"request {request_id} was cancelled")
                    if not isinstance(chunk, Mapping):
                        raise PersistentControlChannelError("provider stream handler returned a non-object")
                    sent_chunk = True
                    sent_done = chunk.get("done") is True
                    send_frame(
                        sock,
                        {
                            "kind": "stream",
                            "correlation_id": request_id,
                            "ok": True,
                            "done": sent_done,
                            "payload": dict(chunk),
                        },
                        lock=write_lock,
                    )
                    if sent_done:
                        break
                if not sent_chunk or not sent_done:
                    raise PersistentControlChannelError("provider stream ended without a final chunk")
                return
            if self._request_handler_accepts_cancel:
                result = self.request_handler(message_type, payload, session, cancel_event)  # type: ignore[misc]
            else:
                result = self.request_handler(message_type, payload, session)
            if cancel_event.is_set():
                raise RequestCancelled(f"request {request_id} was cancelled")
            response = {"kind": "response", "correlation_id": request_id, "ok": True, "payload": result}
        except Exception as exc:
            response = {
                "kind": "response",
                "correlation_id": request_id,
                "ok": False,
                "error": f"{type(exc).__name__}: {str(exc)[:400]}",
            }
        try:
            send_frame(sock, response, lock=write_lock)
        except OSError:
            pass
        finally:
            with active_lock:
                active.pop(request_id, None)

    def stop(self) -> None:
        self._stop.set()
        # recv_frame() blocks on the provider socket. Shutdown wakes that
        # reader so service managers can drain/stop the client promptly.
        with self._socket_lock:
            sock = self._active_socket
        if sock is not None:
            try:
                sock.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
            finally:
                try:
                    sock.close()
                except OSError:
                    pass

    def serve_forever(self) -> None:
        backoff = self.min_backoff_seconds
        while not self._stop.is_set():
            sock: socket.socket | None = None
            try:
                sock = self.connector()
                with self._socket_lock:
                    self._active_socket = sock
                challenge = recv_frame(sock)
                if challenge.get("kind") != "challenge":
                    raise PersistentControlChannelError("server did not issue session challenge")
                session = self.handshake(sock, challenge)
                backoff = self.min_backoff_seconds
                write_lock = threading.Lock()
                active_lock = threading.Lock()
                active: dict[str, threading.Event] = {}
                workers: list[threading.Thread] = []
                while not self._stop.is_set():
                    frame = recv_frame(sock)
                    kind = frame.get("kind")
                    if kind == "ping":
                        send_frame(sock, {"kind": "pong", "sent_at": frame.get("sent_at")}, lock=write_lock)
                        continue
                    if kind == "cancel":
                        request_id = _validate_request_id(str(frame.get("request_id") or ""))
                        with active_lock:
                            cancel_event = active.get(request_id)
                        if cancel_event is not None:
                            cancel_event.set()
                        continue
                    if kind != "request":
                        raise PersistentControlChannelError("unexpected control-plane frame")
                    request_id = _validate_request_id(str(frame.get("request_id") or ""))
                    cancel_event = threading.Event()
                    with active_lock:
                        if request_id in active:
                            raise PersistentControlChannelError("duplicate provider request id")
                        active[request_id] = cancel_event
                    worker = threading.Thread(
                        target=self._dispatch_request,
                        kwargs={
                            "sock": sock,
                            "frame": frame,
                            "session": session,
                            "write_lock": write_lock,
                            "cancel_event": cancel_event,
                            "active": active,
                            "active_lock": active_lock,
                        },
                        name=f"ComputeMesh-provider-request-{request_id[:24]}",
                        daemon=True,
                    )
                    workers.append(worker)
                    worker.start()
            except Exception:
                for cancel_event in tuple(active.values()) if 'active' in locals() else ():
                    cancel_event.set()
                for worker in tuple(workers) if 'workers' in locals() else ():
                    worker.join(0.5)
                if self._stop.wait(backoff):
                    break
                backoff = min(self.max_backoff_seconds, max(self.min_backoff_seconds, backoff * 2))
            finally:
                with self._socket_lock:
                    if self._active_socket is sock:
                        self._active_socket = None
                for cancel_event in tuple(active.values()) if 'active' in locals() else ():
                    cancel_event.set()
                for worker in tuple(workers) if 'workers' in locals() else ():
                    worker.join(0.5)
                if sock is not None:
                    try:
                        sock.close()
                    except OSError:
                        pass


def tls_client_connector(*, host: str, port: int, ca_file: str, server_hostname: str | None = None, timeout_seconds: float = 10.0) -> Callable[[], socket.socket]:
    """Create a connector that verifies the control-plane TLS server certificate."""
    context = ssl.create_default_context(ssl.Purpose.SERVER_AUTH, cafile=ca_file)
    context.check_hostname = True
    context.verify_mode = ssl.CERT_REQUIRED
    hostname = server_hostname or host

    def connect() -> socket.socket:
        raw = socket.create_connection((host, port), timeout=timeout_seconds)
        try:
            wrapped = context.wrap_socket(raw, server_hostname=hostname)
            wrapped.settimeout(None)
            return wrapped
        except Exception:
            raw.close()
            raise

    return connect
