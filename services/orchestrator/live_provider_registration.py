"""Populate LiveSharedRuntimeRegistry from authenticated provider push messages."""
from __future__ import annotations

from dataclasses import dataclass
import threading
from typing import Any

from protocol.control import ControlEnvelope, parse_control_envelope
from protocol.node_identity import AUTH_METHOD, Ed25519ChallengeVerifier
from protocol.node_session import NodeSession, NodeSessionState, SessionSnapshot
from protocol.session_contracts import SessionMessageContractValidator
from protocol.session_wire import BenchmarkAcceptancePolicy, NodeSessionWireHandler
from runtime.llama.rpc_spike import RpcEndpoint
from services.orchestrator.live_shared_runtime import LiveNodeState, LiveSharedRuntimeRegistry
from services.orchestrator.persistent_control_channel import (
    AcceptedProviderSession,
    PersistentControlChannelError,
    PersistentNodeConnection,
    PersistentNodeControlClient,
    recv_frame,
    send_frame,
)

_PROVIDER_PUSH_MESSAGES = frozenset({"NodeProfileUpdate", "RuntimeAdvertisement", "BenchmarkReport", "DrainRequest"})


@dataclass
class _PartialNode:
    session: SessionSnapshot
    profile: dict[str, Any] | None = None
    prefill: dict[str, Any] | None = None
    decode: dict[str, Any] | None = None
    rpc_endpoint: RpcEndpoint | None = None
    llama_build_number: int | None = None
    llama_build_commit: str | None = None


class LiveProviderRegistration:
    """Accumulate authenticated provider telemetry until a schedulable node is complete."""

    def __init__(self, registry: LiveSharedRuntimeRegistry) -> None:
        self.registry = registry
        self._lock = threading.RLock()
        self._nodes: dict[str, _PartialNode] = {}

    def note_session(self, session: SessionSnapshot) -> None:
        if not session.node_id:
            raise PersistentControlChannelError("live provider session has no node identity")
        with self._lock:
            current = self._nodes.get(session.node_id)
            if current is None:
                self._nodes[session.node_id] = _PartialNode(session=session)
            else:
                current.session = session
            self._publish_if_complete(session.node_id)

    def consume(self, envelope: ControlEnvelope, snapshot: SessionSnapshot) -> None:
        node_id = snapshot.node_id
        if not node_id or envelope.actor_id != node_id:
            raise PersistentControlChannelError("provider push actor does not match authenticated node")
        payload = dict(envelope.payload)
        with self._lock:
            current = self._nodes.setdefault(node_id, _PartialNode(session=snapshot))
            current.session = snapshot
            if envelope.message_type == "NodeProfileUpdate":
                if payload.get("node_id") != node_id:
                    raise PersistentControlChannelError("profile node_id does not match authenticated node")
                current.profile = payload
            elif envelope.message_type == "RuntimeAdvertisement":
                if payload.get("node_id") != node_id:
                    raise PersistentControlChannelError("runtime advertisement node_id mismatch")
                if current.profile is None or payload.get("profile_revision") != current.profile.get("profile_revision"):
                    raise PersistentControlChannelError("runtime advertisement is not bound to current profile revision")
                rpc = payload["rpc"]
                current.rpc_endpoint = RpcEndpoint(str(rpc["host"]), int(rpc["port"]))
                current.llama_build_number = int(payload["llama_build_number"])
                current.llama_build_commit = str(payload["llama_build_commit"])
            elif envelope.message_type == "BenchmarkReport":
                if current.profile is None or payload.get("profile_revision") != current.profile.get("profile_revision"):
                    raise PersistentControlChannelError("benchmark is not bound to current profile revision")
                name = payload.get("benchmark_name")
                if name == "llama_cpp_prefill":
                    current.prefill = payload
                elif name == "llama_cpp_decode":
                    current.decode = payload
                elif name == "tcp_network_path":
                    conditions = payload.get("conditions", {})
                    local_id = conditions.get("local_node_id")
                    peer_id = conditions.get("peer_node_id")
                    if local_id != node_id or not isinstance(peer_id, str) or peer_id == node_id:
                        raise PersistentControlChannelError("network benchmark lacks authenticated local/peer binding")
                    self.registry.register_network_result(node_id, peer_id, payload)
            elif envelope.message_type == "DrainRequest":
                # The session state already changed to DRAINING in NodeSessionWireHandler.
                pass
            else:
                raise PersistentControlChannelError("unsupported provider push message")
            self._publish_if_complete(node_id)

    def _publish_if_complete(self, node_id: str) -> None:
        current = self._nodes[node_id]
        if (
            current.profile is None
            or current.prefill is None
            or current.decode is None
            or current.rpc_endpoint is None
            or current.llama_build_number is None
            or current.llama_build_commit is None
        ):
            return
        self.registry.register_node(
            LiveNodeState(
                session=current.session,
                profile=dict(current.profile),
                prefill=dict(current.prefill),
                decode=dict(current.decode),
                rpc_endpoint=current.rpc_endpoint,
                llama_build_number=current.llama_build_number,
                llama_build_commit=current.llama_build_commit,
            )
        )


class LivePersistentNodeConnection(PersistentNodeConnection):
    """Persistent connection that also accepts authenticated provider push envelopes."""

    def __init__(self, *, wire_handler: NodeSessionWireHandler, registration: LiveProviderRegistration, **kwargs: Any) -> None:
        self.wire_handler = wire_handler
        self.registration = registration
        super().__init__(**kwargs)

    def _handle_runtime_advertisement(self, envelope: ControlEnvelope) -> SessionSnapshot:
        SessionMessageContractValidator().validate(envelope.message_type, envelope.payload)
        snapshot = self.wire_handler.session.snapshot()
        if snapshot.state not in {NodeSessionState.PROFILE_SYNCED, NodeSessionState.READY}:
            raise PersistentControlChannelError("runtime advertisement requires a synced provider profile")
        if envelope.actor_id != snapshot.node_id or envelope.expected_revision != snapshot.revision:
            raise PersistentControlChannelError("runtime advertisement session binding mismatch")
        payload = envelope.payload
        if payload["node_id"] != snapshot.node_id or payload["profile_revision"] != snapshot.profile_revision:
            raise PersistentControlChannelError("runtime advertisement profile binding mismatch")
        return snapshot

    def _read_loop(self) -> None:
        try:
            while not self._closed.is_set():
                frame = recv_frame(self.sock)
                kind = frame.get("kind")
                if kind == "pong":
                    self._last_pong = __import__("time").monotonic()
                    continue
                if kind == "response":
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
                    continue
                if kind != "envelope" or not isinstance(frame.get("document"), dict):
                    raise PersistentControlChannelError("unexpected provider frame")
                envelope = parse_control_envelope(frame["document"])
                if envelope.message_type not in _PROVIDER_PUSH_MESSAGES:
                    raise PersistentControlChannelError("message is not allowed after provider handshake")
                if envelope.message_type == "RuntimeAdvertisement":
                    snapshot = self._handle_runtime_advertisement(envelope)
                else:
                    snapshot = self.wire_handler.handle(envelope)
                self.session = snapshot
                self.registration.consume(envelope, snapshot)
                send_frame(self.sock, {"kind": "session_ack", "state": snapshot.state.value, "revision": snapshot.revision}, lock=self._write_lock)
        except Exception:
            self.close()


def accept_live_authenticated_provider(
    *,
    sock: Any,
    verifier: Ed25519ChallengeVerifier,
    benchmark_policy: BenchmarkAcceptancePolicy,
    control_client: PersistentNodeControlClient,
    registration: LiveProviderRegistration,
    control_plane_id: str,
    control_plane_capabilities: tuple[str, ...],
    required_capabilities: tuple[str, ...] = ("execution_attestation_v1",),
    handshake_timeout_seconds: float = 15.0,
) -> AcceptedProviderSession:
    """Authenticate and retain the session wire handler for subsequent provider pushes."""
    import time

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
    connection = LivePersistentNodeConnection(
        sock=sock,
        session=snapshot,
        control_plane_id=control_plane_id,
        wire_handler=handler,
        registration=registration,
    )
    registration.note_session(snapshot)
    control_client.register(connection)
    return AcceptedProviderSession(snapshot, connection)
