"""Regression tests for bidirectional mTLS tunnel EOF and abort behavior.

These tests use in-memory socket doubles. They do NOT replace the required
source-bound TLS handshake, rogue-certificate and real loopback echo tests.
"""
from __future__ import annotations

import socket
import threading
import time
import unittest

from runtime.network.mesh_transport import MeshTunnelClient, MeshTunnelServer


class _Reader:
    def __init__(self, chunks: tuple[bytes, ...], *, fail: bool = False) -> None:
        self.chunks = list(chunks)
        self.fail = fail
        self.timeout = None

    def settimeout(self, value: float) -> None:
        self.timeout = value

    def recv_into(self, buf: bytearray) -> int:
        if self.fail:
            raise OSError("injected transport failure")
        data = self.chunks.pop(0) if self.chunks else b""
        buf[: len(data)] = data
        return len(data)


class _Writer:
    def __init__(self, *, fail: bool = False) -> None:
        self.payloads: list[bytes] = []
        self.shutdown_calls: list[int] = []
        self.fail = fail

    def sendall(self, data: bytes) -> None:
        if self.fail:
            raise OSError("injected send failure")
        self.payloads.append(bytes(data))

    def shutdown(self, how: int) -> None:
        self.shutdown_calls.append(how)


class TestMtlsTunnelDuplexDrain(unittest.TestCase):
    def test_graceful_eof_does_not_abort_reverse_direction(self) -> None:
        for tunnel_class, direction, counter in (
            (MeshTunnelServer, "c2t", "total_bytes_received"),
            (MeshTunnelServer, "t2c", "total_bytes_sent"),
            (MeshTunnelClient, "a2s", "total_bytes_sent"),
            (MeshTunnelClient, "s2a", "total_bytes_received"),
        ):
            with self.subTest(tunnel=tunnel_class.__name__, direction=direction):
                tunnel = object.__new__(tunnel_class)
                tunnel._running = True
                setattr(tunnel, counter, 0)
                reader = _Reader((b"hello", b""))
                writer = _Writer()
                stop = threading.Event()
                tunnel._pipe(reader, writer, direction, stop)
                self.assertEqual(writer.payloads, [b"hello"])
                self.assertEqual(writer.shutdown_calls, [socket.SHUT_WR])
                self.assertEqual(getattr(tunnel, counter), 5)
                self.assertFalse(stop.is_set(), "clean EOF must allow reply to drain")

    def test_delayed_reverse_data_survives_half_close_on_socketpairs(self) -> None:
        # No external network needed; use kernel socket pairs to exercise
        # simultaneous real recv_into/sendall and TCP-style half-close.
        for tunnel_class, forward, reverse in (
            (MeshTunnelServer, "c2t", "t2c"),
            (MeshTunnelClient, "a2s", "s2a"),
        ):
            with self.subTest(tunnel=tunnel_class.__name__):
                app_end, tunnel_app_end = socket.socketpair()
                tunnel_echo_end, echo_end = socket.socketpair()
                stop = threading.Event()
                tunnel = object.__new__(tunnel_class)
                tunnel._running = True
                tunnel.total_bytes_sent = 0
                tunnel.total_bytes_received = 0
                outgoing = threading.Thread(
                    target=tunnel._pipe,
                    args=(tunnel_app_end, tunnel_echo_end, forward, stop),
                    daemon=True,
                )
                incoming = threading.Thread(
                    target=tunnel._pipe,
                    args=(tunnel_echo_end, tunnel_app_end, reverse, stop),
                    daemon=True,
                )
                try:
                    app_end.settimeout(2.0)
                    echo_end.settimeout(2.0)
                    outgoing.start()
                    incoming.start()
                    app_end.sendall(b"PING")
                    app_end.shutdown(socket.SHUT_WR)
                    self.assertEqual(echo_end.recv(16), b"PING")
                    # The request has ended; reverse traffic is delayed.
                    time.sleep(0.06)
                    echo_end.sendall(b"ECHO:PING")
                    echo_end.shutdown(socket.SHUT_WR)
                    self.assertEqual(app_end.recv(64), b"ECHO:PING")
                    outgoing.join(timeout=2.0)
                    incoming.join(timeout=2.0)
                    self.assertFalse(outgoing.is_alive())
                    self.assertFalse(incoming.is_alive())
                    self.assertFalse(stop.is_set(), "graceful EOF must not abort")
                finally:
                    stop.set()
                    for sock in (app_end, tunnel_app_end, tunnel_echo_end, echo_end):
                        sock.close()
                    if outgoing.ident is not None:
                        outgoing.join(timeout=1.0)
                    if incoming.ident is not None:
                        incoming.join(timeout=1.0)

    def test_socket_read_error_aborts_both_directions(self) -> None:
        for tunnel_class, direction in (
            (MeshTunnelServer, "c2t"),
            (MeshTunnelClient, "a2s"),
        ):
            with self.subTest(tunnel=tunnel_class.__name__):
                tunnel = object.__new__(tunnel_class)
                tunnel._running = True
                writer = _Writer()
                stop = threading.Event()
                tunnel._pipe(_Reader((), fail=True), writer, direction, stop)
                self.assertTrue(stop.is_set())

    def test_socket_write_error_aborts_both_directions(self) -> None:
        for tunnel_class, direction in (
            (MeshTunnelServer, "c2t"),
            (MeshTunnelClient, "a2s"),
        ):
            with self.subTest(tunnel=tunnel_class.__name__):
                tunnel = object.__new__(tunnel_class)
                tunnel._running = True
                setattr(tunnel, "total_bytes_received" if direction == "c2t"
                        else "total_bytes_sent", 0)
                stop = threading.Event()
                tunnel._pipe(_Reader((b"hello",)), _Writer(fail=True), direction, stop)
                self.assertTrue(stop.is_set())


if __name__ == "__main__":
    unittest.main()
