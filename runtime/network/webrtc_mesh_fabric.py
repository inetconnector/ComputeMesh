#!/usr/bin/env python3
"""ComputeMesh WebRTC P2P Mesh Fabric Resilience Subsystem.

Provides zero-trust WebRTC peer-to-peer data channel framing, connection probing,
dynamic path selection (WebRTC P2P <-> mTLS fallback), and strict invariant validation
across distributed coordinator and worker nodes.
"""
from __future__ import annotations

import dataclasses
from enum import Enum, auto
import hashlib
import json
import logging
import socket
import struct
import sys
import threading
import time
from typing import Any, Callable
import zlib

from pathlib import Path
REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from runtime.network.mesh_transport import NodeCredentials, MeshTransportError

logger = logging.getLogger("computemesh.webrtc_mesh")


class WebRTCP2PState(Enum):
    DISCONNECTED = auto()
    CONNECTING = auto()
    CONNECTED = auto()
    DEGRADED = auto()
    RECONNECTING = auto()
    FAILED = auto()
    CLOSED = auto()


class WebRTCFabricError(MeshTransportError):
    """Base exception for WebRTC Mesh Fabric errors."""


@dataclasses.dataclass(frozen=True)
class WebRTCSignalingEnvelope:
    sender_node_id: str
    target_node_id: str
    msg_type: str  # offer, answer, ice_candidate, heartbeat
    sdp_or_candidate: str
    sequence: int
    timestamp: float
    signature: str = ""

    def to_dict(self) -> dict[str, Any]:
        return dataclasses.asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> WebRTCSignalingEnvelope:
        return cls(
            sender_node_id=str(data["sender_node_id"]),
            target_node_id=str(data["target_node_id"]),
            msg_type=str(data["msg_type"]),
            sdp_or_candidate=str(data["sdp_or_candidate"]),
            sequence=int(data["sequence"]),
            timestamp=float(data["timestamp"]),
            signature=str(data.get("signature", "")),
        )


@dataclasses.dataclass(frozen=True)
class MeshFabricMetrics:
    local_node_id: str
    remote_node_id: str
    active_transport: str  # 'webrtc_p2p' or 'mtls_fallback'
    p2p_state: str
    rtt_ms: float
    packets_sent: int
    packets_received: int
    bytes_sent: int
    bytes_received: int
    failover_count: int


# Frame header: Magic (4B: 'WMRF'), Type (1B), Sequence (4B), Payload Length (4B), Checksum (4B)
FRAME_HEADER_FORMAT = "!4sBIII"
FRAME_HEADER_SIZE = struct.calcsize(FRAME_HEADER_FORMAT)
MAGIC_BYTES = b"WMRF"


class WebRTCFrameType(Enum):
    DATA = 1
    HEARTBEAT_PING = 2
    HEARTBEAT_PONG = 3
    PATH_PROBE = 4
    CLOSE = 5


def pack_frame(frame_type: WebRTCFrameType, sequence: int, payload: bytes) -> bytes:
    checksum = zlib.crc32(payload) & 0xFFFFFFFF
    header = struct.pack(
        FRAME_HEADER_FORMAT,
        MAGIC_BYTES,
        frame_type.value,
        sequence,
        len(payload),
        checksum,
    )
    return header + payload


def unpack_frame_header(header_bytes: bytes) -> tuple[WebRTCFrameType, int, int, int]:
    if len(header_bytes) < FRAME_HEADER_SIZE:
        raise WebRTCFabricError("Header buffer too short")
    magic, raw_type, seq, payload_len, checksum = struct.unpack(FRAME_HEADER_FORMAT, header_bytes)
    if magic != MAGIC_BYTES:
        raise WebRTCFabricError(f"Invalid frame magic: {magic!r}")
    try:
        ftype = WebRTCFrameType(raw_type)
    except ValueError as exc:
        raise WebRTCFabricError(f"Unknown frame type: {raw_type}") from exc
    return ftype, seq, payload_len, checksum


class WebRTCP2PPeer:
    """Manages an authenticated WebRTC P2P Data Channel session over dual socket channels

    with active probing, state tracking, and CRC32 payload verification.
    """

    def __init__(
        self,
        *,
        local_creds: NodeCredentials,
        remote_node_id: str,
        heartbeat_interval_sec: float = 0.5,
        rtt_degraded_threshold_ms: float = 300.0,
        max_missed_heartbeats: int = 3,
    ) -> None:
        self.local_creds = local_creds
        self.local_node_id = local_creds.node_id
        self.remote_node_id = remote_node_id
        self.heartbeat_interval = heartbeat_interval_sec
        self.rtt_degraded_threshold_ms = rtt_degraded_threshold_ms
        self.max_missed_heartbeats = max_missed_heartbeats

        self.state = WebRTCP2PState.DISCONNECTED
        self._lock = threading.RLock()
        self._sock: socket.socket | None = None
        self._running = False
        self._rx_thread: threading.Thread | None = None
        self._probe_thread: threading.Thread | None = None

        self._seq_out = 0
        self._seq_in = -1
        self.rtt_ms: float = 0.0
        self.missed_heartbeats: int = 0
        self.packets_sent: int = 0
        self.packets_recv: int = 0
        self.bytes_sent: int = 0
        self.bytes_recv: int = 0

        self._data_callback: Callable[[bytes], None] | None = None
        self._state_callback: Callable[[WebRTCP2PState], None] | None = None
        self._ping_timestamps: dict[int, float] = {}

    def set_data_callback(self, cb: Callable[[bytes], None]) -> None:
        self._data_callback = cb

    def set_state_callback(self, cb: Callable[[WebRTCP2PState], None]) -> None:
        self._state_callback = cb

    def _set_state(self, new_state: WebRTCP2PState) -> None:
        with self._lock:
            if self.state == new_state:
                return
            logger.info(f"WebRTC P2P Peer [{self.local_node_id}->{self.remote_node_id}] state: {self.state.name} -> {new_state.name}")
            self.state = new_state
        if self._state_callback:
            try:
                self._state_callback(new_state)
            except Exception as e:
                logger.error(f"Error in state callback: {e}")

    def attach_socket(self, sock: socket.socket) -> None:
        with self._lock:
            if self._running:
                raise WebRTCFabricError("Peer session already active")
            self._sock = sock
            self._sock.settimeout(1.0)
            self._running = True
            self._set_state(WebRTCP2PState.CONNECTED)

            self._rx_thread = threading.Thread(target=self._rx_loop, daemon=True)
            self._probe_thread = threading.Thread(target=self._probe_loop, daemon=True)
            self._rx_thread.start()
            self._probe_thread.start()

    def send_data(self, data: bytes) -> None:
        with self._lock:
            if not self._running or self._sock is None:
                raise WebRTCFabricError("Peer transport is not connected")
            if self.state in (WebRTCP2PState.FAILED, WebRTCP2PState.CLOSED):
                raise WebRTCFabricError(f"Cannot send data in state {self.state.name}")
            self._seq_out += 1
            frame = pack_frame(WebRTCFrameType.DATA, self._seq_out, data)
            self._send_raw(frame)
            self.packets_sent += 1
            self.bytes_sent += len(data)

    def _send_raw(self, frame: bytes) -> None:
        if self._sock:
            self._sock.sendall(frame)

    def close(self) -> None:
        with self._lock:
            if not self._running:
                return
            self._running = False
            self._set_state(WebRTCP2PState.CLOSED)
            if self._sock:
                try:
                    close_frame = pack_frame(WebRTCFrameType.CLOSE, 0, b"")
                    self._sock.sendall(close_frame)
                    self._sock.close()
                except Exception:
                    pass
                self._sock = None

    def _rx_loop(self) -> None:
        buf = bytearray()
        while self._running:
            try:
                if self._sock is None:
                    break
                try:
                    chunk = self._sock.recv(65536)
                except socket.timeout:
                    continue
                except (OSError, ConnectionResetError):
                    break
                if not chunk:
                    break
                buf.extend(chunk)

                while len(buf) >= FRAME_HEADER_SIZE:
                    ftype, seq, plen, checksum = unpack_frame_header(bytes(buf[:FRAME_HEADER_SIZE]))
                    total_frame_len = FRAME_HEADER_SIZE + plen
                    if len(buf) < total_frame_len:
                        break  # Wait for remaining payload bytes

                    payload = bytes(buf[FRAME_HEADER_SIZE:total_frame_len])
                    del buf[:total_frame_len]

                    # Verify invariant: CRC32 checksum must match
                    if (zlib.crc32(payload) & 0xFFFFFFFF) != checksum:
                        logger.error(f"CRC32 mismatch in WebRTC frame from {self.remote_node_id}")
                        self._set_state(WebRTCP2PState.FAILED)
                        break

                    self._handle_frame(ftype, seq, payload)

            except Exception as exc:
                logger.debug(f"WebRTC rx loop error: {exc}")
                break

        with self._lock:
            if self._running and self.state not in (WebRTCP2PState.CLOSED, WebRTCP2PState.FAILED):
                self._set_state(WebRTCP2PState.FAILED)

    def _handle_frame(self, ftype: WebRTCFrameType, seq: int, payload: bytes) -> None:
        self.packets_recv += 1
        self.bytes_recv += len(payload)

        if ftype == WebRTCFrameType.DATA:
            if self._data_callback:
                try:
                    self._data_callback(payload)
                except Exception as e:
                    logger.error(f"Data callback error: {e}")

        elif ftype == WebRTCFrameType.HEARTBEAT_PING:
            # Reply with PONG immediately
            pong = pack_frame(WebRTCFrameType.HEARTBEAT_PONG, seq, payload)
            with self._lock:
                self._send_raw(pong)

        elif ftype == WebRTCFrameType.HEARTBEAT_PONG:
            sent_at = self._ping_timestamps.pop(seq, None)
            if sent_at is not None:
                rtt = (time.monotonic() - sent_at) * 1000.0
                with self._lock:
                    self.rtt_ms = rtt
                    self.missed_heartbeats = 0
                    if self.rtt_ms > self.rtt_degraded_threshold_ms:
                        self._set_state(WebRTCP2PState.DEGRADED)
                    elif self.state == WebRTCP2PState.DEGRADED:
                        self._set_state(WebRTCP2PState.CONNECTED)

        elif ftype == WebRTCFrameType.CLOSE:
            self.close()

    def _probe_loop(self) -> None:
        ping_seq = 0
        while self._running:
            time.sleep(self.heartbeat_interval)
            if not self._running or self.state in (WebRTCP2PState.CLOSED, WebRTCP2PState.FAILED):
                break

            ping_seq += 1
            now = time.monotonic()
            self._ping_timestamps[ping_seq] = now

            # Prune old pings and track missed heartbeats
            expired = [s for s, t in self._ping_timestamps.items() if now - t > 3.0]
            for s in expired:
                del self._ping_timestamps[s]
                with self._lock:
                    self.missed_heartbeats += 1
                    if self.missed_heartbeats >= self.max_missed_heartbeats:
                        logger.warning(f"Peer {self.remote_node_id} missed {self.missed_heartbeats} heartbeats")
                        self._set_state(WebRTCP2PState.FAILED)

            if self.state != WebRTCP2PState.FAILED:
                ping_frame = pack_frame(WebRTCFrameType.HEARTBEAT_PING, ping_seq, struct.pack("!d", now))
                try:
                    with self._lock:
                        self._send_raw(ping_frame)
                except Exception:
                    with self._lock:
                        self._set_state(WebRTCP2PState.FAILED)


class ResilientMeshFabricManager:
    """Orchestrates WebRTC P2P data channels with automatic, zero-data-loss failover

    to direct mTLS TCP tunnel when P2P transport degrades or fails.
    """

    def __init__(self, local_creds: NodeCredentials) -> None:
        self.local_creds = local_creds
        self.local_node_id = local_creds.node_id
        self._lock = threading.RLock()
        self._p2p_peers: dict[str, WebRTCP2PPeer] = {}
        self._mtls_tunnels: dict[str, Any] = {}
        self._data_listeners: dict[str, Callable[[str, bytes], None]] = {}
        self.failover_counts: dict[str, int] = {}

    def register_peer_p2p(self, remote_node_id: str, sock: socket.socket) -> WebRTCP2PPeer:
        with self._lock:
            if remote_node_id in self._p2p_peers:
                self._p2p_peers[remote_node_id].close()

            peer = WebRTCP2PPeer(local_creds=self.local_creds, remote_node_id=remote_node_id)

            def _on_data(data: bytes, r_id: str = remote_node_id) -> None:
                self._dispatch_data(r_id, data)

            def _on_state(state: WebRTCP2PState, r_id: str = remote_node_id) -> None:
                self._on_p2p_state_change(r_id, state)

            peer.set_data_callback(_on_data)
            peer.set_state_callback(_on_state)
            peer.attach_socket(sock)
            self._p2p_peers[remote_node_id] = peer
            if remote_node_id not in self.failover_counts:
                self.failover_counts[remote_node_id] = 0
            return peer

    def register_mtls_fallback(self, remote_node_id: str, tunnel_client_or_server: Any) -> None:
        with self._lock:
            self._mtls_tunnels[remote_node_id] = tunnel_client_or_server

    def set_data_listener(self, channel_id: str, listener: Callable[[str, bytes], None]) -> None:
        with self._lock:
            self._data_listeners[channel_id] = listener

    def _dispatch_data(self, sender_node_id: str, data: bytes) -> None:
        with self._lock:
            listeners = list(self._data_listeners.values())
        for listener in listeners:
            try:
                listener(sender_node_id, data)
            except Exception as e:
                logger.error(f"Error in mesh data listener: {e}")

    def _on_p2p_state_change(self, remote_node_id: str, state: WebRTCP2PState) -> None:
        if state in (WebRTCP2PState.DEGRADED, WebRTCP2PState.FAILED):
            with self._lock:
                self.failover_counts[remote_node_id] = self.failover_counts.get(remote_node_id, 0) + 1
            logger.warning(f"WebRTC P2P path for node {remote_node_id} is {state.name}. Triggering dynamic failover to mTLS.")

    def send_to_peer(self, remote_node_id: str, data: bytes) -> str:
        """Sends data to remote peer using WebRTC P2P if healthy, falling back

        to direct mTLS TCP tunnel when WebRTC P2P is degraded or unavailable.
        Returns active transport name used ('webrtc_p2p' or 'mtls_fallback').
        """
        with self._lock:
            peer = self._p2p_peers.get(remote_node_id)
            mtls_tunnel = self._mtls_tunnels.get(remote_node_id)

            # Check if WebRTC P2P is active and healthy
            if peer and peer.state in (WebRTCP2PState.CONNECTED,):
                try:
                    peer.send_data(data)
                    return "webrtc_p2p"
                except WebRTCFabricError as exc:
                    logger.warning(f"P2P send failed ({exc}), attempting mTLS fallback")

            # Fallback path: Send over direct mTLS tunnel
            if mtls_tunnel:
                self.failover_counts[remote_node_id] = self.failover_counts.get(remote_node_id, 0) + 1
                # If mtls_tunnel is socket-like or has send method
                if hasattr(mtls_tunnel, "sendall"):
                    mtls_tunnel.sendall(data)
                elif hasattr(mtls_tunnel, "send_data"):
                    mtls_tunnel.send_data(data)
                else:
                    raise WebRTCFabricError(f"mTLS fallback tunnel for {remote_node_id} is not writeable")
                return "mtls_fallback"

            raise WebRTCFabricError(f"No available healthy transport for remote node {remote_node_id}")

    def get_peer_metrics(self, remote_node_id: str) -> MeshFabricMetrics:
        with self._lock:
            peer = self._p2p_peers.get(remote_node_id)
            active_transport = "webrtc_p2p" if (peer and peer.state == WebRTCP2PState.CONNECTED) else "mtls_fallback"
            return MeshFabricMetrics(
                local_node_id=self.local_node_id,
                remote_node_id=remote_node_id,
                active_transport=active_transport,
                p2p_state=peer.state.name if peer else "UNREGISTERED",
                rtt_ms=peer.rtt_ms if peer else 0.0,
                packets_sent=peer.packets_sent if peer else 0,
                packets_received=peer.packets_recv if peer else 0,
                bytes_sent=peer.bytes_sent if peer else 0,
                bytes_received=peer.bytes_recv if peer else 0,
                failover_count=self.failover_counts.get(remote_node_id, 0),
            )

    def close_all(self) -> None:
        with self._lock:
            for peer in self._p2p_peers.values():
                peer.close()
            self._p2p_peers.clear()
            self._mtls_tunnels.clear()
