"""Regression tests for bidirectional mTLS tunnel EOF and abort behavior.

These tests use in-memory socket doubles. They do NOT replace the required
source-bound TLS handshake, rogue-certificate and real loopback echo tests.
"""
from __future__ import annotations

import socket
import threading
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
