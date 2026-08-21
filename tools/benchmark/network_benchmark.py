#!/usr/bin/env python3
"""ComputeMesh M0 TCP network microbenchmark.

This tool measures application-level connection setup, small-frame RTT, upload
throughput, and download throughput. The server defaults to loopback and has no
authentication; it is intended only for controlled lab/LAN experiments.

Newer servers can self-report a lab node ID over the same unauthenticated
benchmark connection. This improves evidence traceability but is not a security
identity proof.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import socket
import struct
import time
import uuid
from typing import Any

SCHEMA_VERSION = 1
HEADER = struct.Struct("!cQ")
CHUNK_BYTES = 256 * 1024
DEFAULT_MAX_TRANSFER = 64 * 1024 * 1024
MAX_NODE_ID_BYTES = 512


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _node_id(value: str | None, label: str, *, required: bool = False) -> str | None:
    if value is None:
        if required:
            raise ValueError(f"{label} is required")
        return None
    if not isinstance(value, str):
        raise ValueError(f"{label} must be a string")
    normalized = value.strip()
    if not normalized or len(normalized) > 128 or any(ord(ch) < 32 or ord(ch) == 127 for ch in normalized):
        raise ValueError(f"{label} must be 1..128 printable characters")
    if len(normalized.encode("utf-8")) > MAX_NODE_ID_BYTES:
        raise ValueError(f"{label} UTF-8 encoding is too large")
    return normalized


def percentile(samples: list[float], q: float) -> float:
    if not samples:
        raise ValueError("samples must not be empty")
    if not 0.0 <= q <= 1.0:
        raise ValueError("q must be between 0 and 1")
    ordered = sorted(samples)
    if len(ordered) == 1:
        return ordered[0]
    pos = (len(ordered) - 1) * q
    lo = int(pos)
    hi = min(lo + 1, len(ordered) - 1)
    fraction = pos - lo
    return ordered[lo] * (1.0 - fraction) + ordered[hi] * fraction


def recv_exact(sock: socket.socket, size: int) -> bytes:
    chunks: list[bytes] = []
    remaining = size
    while remaining:
        chunk = sock.recv(min(remaining, CHUNK_BYTES))
        if not chunk:
            raise ConnectionError("peer closed connection")
        chunks.append(chunk)
        remaining -= len(chunk)
    return b"".join(chunks)


def discard_exact(sock: socket.socket, size: int) -> None:
    remaining = size
    while remaining:
        chunk = sock.recv(min(remaining, CHUNK_BYTES))
        if not chunk:
            raise ConnectionError("peer closed connection")
        remaining -= len(chunk)


def send_repeated(sock: socket.socket, size: int, byte: bytes = b"\xA5") -> None:
    block = byte * min(CHUNK_BYTES, max(1, size))
    remaining = size
    while remaining:
        part = block if remaining >= len(block) else block[:remaining]
        sock.sendall(part)
        remaining -= len(part)


def send_header(sock: socket.socket, op: bytes, size: int) -> None:
    sock.sendall(HEADER.pack(op, size))


def recv_header(sock: socket.socket) -> tuple[bytes, int]:
    raw = recv_exact(sock, HEADER.size)
    return HEADER.unpack(raw)


def handle_connection(
    conn: socket.socket,
    *,
    max_transfer_bytes: int = DEFAULT_MAX_TRANSFER,
    node_id: str | None = None,
) -> None:
    reported_node_id = _node_id(node_id, "node_id")
    conn.settimeout(30.0)
    conn.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
    while True:
        try:
            op, size = recv_header(conn)
        except ConnectionError:
            return
        if op == b"Q":
            return
        if op == b"I":
            if size != 0 or reported_node_id is None:
                send_header(conn, b"E", 0)
                continue
            encoded = reported_node_id.encode("utf-8")
            send_header(conn, b"I", len(encoded))
            conn.sendall(encoded)
            continue
        if size > max_transfer_bytes:
            send_header(conn, b"E", 0)
            continue
        if op == b"P":
            payload = recv_exact(conn, size)
            send_header(conn, b"P", size)
            conn.sendall(payload)
        elif op == b"U":
            discard_exact(conn, size)
            send_header(conn, b"A", 0)
        elif op == b"D":
            send_header(conn, b"R", size)
            send_repeated(conn, size, b"\x5A")
        else:
            send_header(conn, b"E", 0)


def serve(
    host: str,
    port: int,
    *,
    max_transfer_bytes: int = DEFAULT_MAX_TRANSFER,
    once: bool = False,
    node_id: str | None = None,
) -> None:
    reported_node_id = _node_id(node_id, "node_id")
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
        listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        listener.bind((host, port))
        listener.listen(8)
        actual_host, actual_port = listener.getsockname()[:2]
        print(f"ComputeMesh network benchmark server listening on {actual_host}:{actual_port}", flush=True)
        while True:
            conn, _ = listener.accept()
            with conn:
                handle_connection(conn, max_transfer_bytes=max_transfer_bytes, node_id=reported_node_id)
            if once:
                return


def _expect(sock: socket.socket, expected: bytes) -> int:
    op, size = recv_header(sock)
    if op == b"E":
        raise RuntimeError("benchmark server rejected request")
    if op != expected:
        raise RuntimeError(f"unexpected server response {op!r}; expected {expected!r}")
    return size


def query_peer_node_id(sock: socket.socket) -> str | None:
    """Return a newer server's unauthenticated lab node ID, or None for legacy servers."""
    send_header(sock, b"I", 0)
    op, size = recv_header(sock)
    if op == b"E":
        return None
    if op != b"I" or not 1 <= size <= MAX_NODE_ID_BYTES:
        raise RuntimeError("invalid benchmark peer identity response")
    try:
        decoded = recv_exact(sock, size).decode("utf-8")
    except UnicodeDecodeError as exc:
        raise RuntimeError("invalid benchmark peer node ID encoding") from exc
    try:
        return _node_id(decoded, "reported peer node_id", required=True)
    except ValueError as exc:
        raise RuntimeError(str(exc)) from exc


def run_client(
    host: str,
    port: int,
    *,
    profile_revision: int,
    local_node_id: str | None = None,
    expected_peer_node_id: str | None = None,
    rtt_samples: int = 20,
    ping_bytes: int = 32,
    transfer_bytes: int = 16 * 1024 * 1024,
    transfer_repeats: int = 3,
    timeout: float = 30.0,
) -> dict[str, Any]:
    if profile_revision < 0:
        raise ValueError("profile_revision must be >= 0")
    if rtt_samples < 1 or transfer_repeats < 1:
        raise ValueError("sample counts must be >= 1")
    if ping_bytes < 1 or transfer_bytes < 1:
        raise ValueError("payload sizes must be >= 1")
    local_id = _node_id(local_node_id, "local_node_id")
    expected_peer = _node_id(expected_peer_node_id, "expected_peer_node_id")

    started_connect = time.perf_counter_ns()
    sock = socket.create_connection((host, port), timeout=timeout)
    connection_setup_ms = (time.perf_counter_ns() - started_connect) / 1_000_000.0
    raw: list[dict[str, Any]] = []
    rtts: list[float] = []
    uploads: list[float] = []
    downloads: list[float] = []
    peer_node_id: str | None = None
    try:
        sock.settimeout(timeout)
        sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        peer_node_id = query_peer_node_id(sock)
        if expected_peer is not None:
            if peer_node_id is None:
                raise RuntimeError("benchmark server did not report a node ID")
            if peer_node_id != expected_peer:
                raise RuntimeError("benchmark peer node ID mismatch")

        ping_payload = b"P" * ping_bytes
        for index in range(rtt_samples):
            started = time.perf_counter_ns()
            send_header(sock, b"P", len(ping_payload))
            sock.sendall(ping_payload)
            echoed_size = _expect(sock, b"P")
            echoed = recv_exact(sock, echoed_size)
            elapsed_ms = (time.perf_counter_ns() - started) / 1_000_000.0
            if echoed != ping_payload:
                raise RuntimeError("ping payload integrity mismatch")
            rtts.append(elapsed_ms)
            raw.append({"kind": "rtt_ms", "sample": index, "value": round(elapsed_ms, 6)})

        for index in range(transfer_repeats):
            started = time.perf_counter_ns()
            send_header(sock, b"U", transfer_bytes)
            send_repeated(sock, transfer_bytes)
            _expect(sock, b"A")
            seconds = (time.perf_counter_ns() - started) / 1_000_000_000.0
            mbps = transfer_bytes * 8.0 / seconds / 1_000_000.0
            uploads.append(mbps)
            raw.append({"kind": "upload_mbps", "sample": index, "value": round(mbps, 6)})

        for index in range(transfer_repeats):
            started = time.perf_counter_ns()
            send_header(sock, b"D", transfer_bytes)
            response_size = _expect(sock, b"R")
            if response_size != transfer_bytes:
                raise RuntimeError("download size mismatch")
            discard_exact(sock, response_size)
            seconds = (time.perf_counter_ns() - started) / 1_000_000_000.0
            mbps = transfer_bytes * 8.0 / seconds / 1_000_000.0
            downloads.append(mbps)
            raw.append({"kind": "download_mbps", "sample": index, "value": round(mbps, 6)})

        send_header(sock, b"Q", 0)
    finally:
        sock.close()

    conditions: dict[str, Any] = {
        "warm_state": "warm",
        "notes": f"TCP application benchmark target={host}:{port}; no transport encryption/authentication",
    }
    if local_id is not None:
        conditions["local_node_id"] = local_id
    if peer_node_id is not None:
        conditions["peer_node_id"] = peer_node_id
        conditions["peer_identity_binding"] = "unauthenticated_server_report_v1"

    return {
        "schema_version": SCHEMA_VERSION,
        "run_id": str(uuid.uuid4()),
        "benchmark_name": "tcp_network_path",
        "captured_at": utc_now(),
        "profile_revision": profile_revision,
        "conditions": conditions,
        "metrics": {
            "connection_setup_ms": round(connection_setup_ms, 6),
            "rtt_ms_p50": round(percentile(rtts, 0.50), 6),
            "rtt_ms_p95": round(percentile(rtts, 0.95), 6),
            "upload_mbps_p50": round(percentile(uploads, 0.50), 6),
            "download_mbps_p50": round(percentile(downloads, 0.50), 6),
            "ping_bytes": ping_bytes,
            "transfer_bytes": transfer_bytes,
            "rtt_samples": rtt_samples,
            "transfer_repeats": transfer_repeats,
        },
        "raw_samples": raw,
    }


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="ComputeMesh M0 TCP network microbenchmark")
    sub = parser.add_subparsers(dest="mode", required=True)

    server = sub.add_parser("server", help="run a lab benchmark server")
    server.add_argument("--bind", default="127.0.0.1")
    server.add_argument("--port", type=int, default=43191)
    server.add_argument("--node-id")
    server.add_argument("--max-transfer-bytes", type=int, default=DEFAULT_MAX_TRANSFER)
    server.add_argument("--once", action="store_true")

    client = sub.add_parser("client", help="measure a server")
    client.add_argument("--host", required=True)
    client.add_argument("--port", type=int, default=43191)
    client.add_argument("--profile-revision", type=int, default=0)
    client.add_argument("--local-node-id")
    client.add_argument("--expected-peer-node-id")
    client.add_argument("--rtt-samples", type=int, default=20)
    client.add_argument("--ping-bytes", type=int, default=32)
    client.add_argument("--transfer-bytes", type=int, default=16 * 1024 * 1024)
    client.add_argument("--transfer-repeats", type=int, default=3)
    client.add_argument("--timeout", type=float, default=30.0)
    client.add_argument("--output-dir", default="artifacts/benchmark")
    client.add_argument("--dry-run", action="store_true")

    args = parser.parse_args(argv)
    if args.mode == "server":
        if not 0 <= args.port <= 65535:
            parser.error("--port must be between 0 and 65535")
        if args.max_transfer_bytes < 1:
            parser.error("--max-transfer-bytes must be >= 1")
        try:
            node_id = _node_id(args.node_id, "--node-id")
        except ValueError as exc:
            parser.error(str(exc))
        serve(args.bind, args.port, max_transfer_bytes=args.max_transfer_bytes, once=args.once, node_id=node_id)
        return 0

    try:
        result = run_client(
            args.host,
            args.port,
            profile_revision=args.profile_revision,
            local_node_id=args.local_node_id,
            expected_peer_node_id=args.expected_peer_node_id,
            rtt_samples=args.rtt_samples,
            ping_bytes=args.ping_bytes,
            transfer_bytes=args.transfer_bytes,
            transfer_repeats=args.transfer_repeats,
            timeout=args.timeout,
        )
    except (ValueError, RuntimeError) as exc:
        parser.error(str(exc))
    if args.dry_run:
        print(json.dumps(result, indent=2, sort_keys=True))
        return 0
    output = Path(args.output_dir) / f"network_{result['run_id']}.json"
    write_json(output, result)
    print(output.resolve())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
