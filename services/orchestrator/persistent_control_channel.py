"""Persistent provider <-> control-plane channel for live ComputeMesh sessions.

The channel deliberately separates transport confidentiality from node identity.
TLS is used for server authentication/encryption when configured; provider identity
is established by the existing ComputeMesh Ed25519 challenge proof and NodeSession
state machine. One long-lived connection carries heartbeats and control requests.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import json
import socket
import ssl
import struct
import threading
import time
from typing import Any, Callable, Mapping

from protocol.control import ControlEnvelope, parse_control_envelope
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

    def _read_loop(self) -> None:
        try:
            while not self._closed.is_set():
                frame = recv_frame(self.sock)
                kind = frame.get("kind")
                if kind == "pong":
                    self._last_pong = time.monotonic()
                    continue
                if kind != "response":
                    raise PersistentControlChannelError("unexpected provider frame")
                correlation_id = frame.get("correlation_id")
                if not isinstance(correlation_id, str):
                    raise PersistentControlChannelError("response lacks correlation_id")
                with self._pending_lock:
                    pending = self._pending.pop(correlation_id, None)
                if pending is None:
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

    def request(self, *, message_type: str, payload: dict[str, Any], timeout_seconds: float) -> dict[str, Any]:
        if not self.alive:
            raise ChannelClosed(f"node {self.node_id} control channel is closed")
        if timeout_seconds <= 0 or timeout_seconds > 300:
            raise ValueError("timeout_seconds must be within (0,300]")
        request_id = f"cp-{time.time_ns():x}-{threading.get_ident():x}"
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

    def live_node_ids(self) -> tuple[str, ...]:
        with self._lock:
            return tuple(sorted(node_id for node_id, connection in self._connections.items() if connection.alive))

    def request(self, *, node_id: str, message_type: str, payload: dict[str, Any], timeout_seconds: float) -> dict[str, Any]:
        with self._lock:
            connection = self._connections.get(node_id)
        if connection is None or not connection.alive:
            raise ChannelClosed(f"node {node_id} has no live persistent control channel")
        return connection.request(message_type=message_type, payload=payload, timeout_seconds=timeout_seconds)

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
        min_backoff_seconds: float = 1.0,
        max_backoff_seconds: float = 30.0,
    ) -> None:
        self.connector = connector
        self.handshake = handshake
        self.request_handler = request_handler
        self.min_backoff_seconds = min_backoff_seconds
        self.max_backoff_seconds = max_backoff_seconds
        self._stop = threading.Event()

    def stop(self) -> None:
        self._stop.set()

    def serve_forever(self) -> None:
        backoff = self.min_backoff_seconds
        while not self._stop.is_set():
            sock: socket.socket | None = None
            try:
                sock = self.connector()
                challenge = recv_frame(sock)
                if challenge.get("kind") != "challenge":
                    raise PersistentControlChannelError("server did not issue session challenge")
                session = self.handshake(sock, challenge)
                backoff = self.min_backoff_seconds
                while not self._stop.is_set():
                    frame = recv_frame(sock)
                    kind = frame.get("kind")
                    if kind == "ping":
                        send_frame(sock, {"kind": "pong", "sent_at": frame.get("sent_at")})
                        continue
                    if kind != "request":
                        raise PersistentControlChannelError("unexpected control-plane frame")
                    request_id = frame.get("request_id")
                    try:
                        if frame.get("session_id") != session.session_id or frame.get("session_revision") != session.revision:
                            raise PersistentControlChannelError("request is bound to another session revision")
                        payload = self.request_handler(str(frame.get("message_type")), dict(frame.get("payload") or {}), session)
                        response = {"kind": "response", "correlation_id": request_id, "ok": True, "payload": payload}
                    except Exception as exc:
                        response = {"kind": "response", "correlation_id": request_id, "ok": False, "error": f"{type(exc).__name__}: {str(exc)[:400]}"}
                    send_frame(sock, response)
            except Exception:
                if self._stop.wait(backoff):
                    break
                backoff = min(self.max_backoff_seconds, max(self.min_backoff_seconds, backoff * 2))
            finally:
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
