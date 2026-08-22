#!/usr/bin/env python3
"""Bounded loopback TCP relay for M1 runtime measurement experiments.

This is a lab instrument, not a ComputeMesh transport. It counts forwarded
bytes, can add bounded deterministic delay/jitter, and can force a connection
drop. It never inspects or persists payload contents.
"""
from __future__ import annotations

import argparse
from dataclasses import asdict, dataclass, replace
from datetime import datetime, timezone
import ipaddress
import json
from pathlib import Path
import queue
import random
import socket
import sys
import threading
import time
from typing import Callable

RFC1918 = tuple(
    ipaddress.ip_network(value)
    for value in ("10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16")
)
DEFAULT_CHUNK_BYTES = 64 * 1024
DEFAULT_MAX_BUFFER_BYTES = 8 * 1024 * 1024
_SENTINEL = object()


class RelayError(RuntimeError):
    pass


@dataclass(frozen=True)
class PrivateEndpoint:
    host: str
    port: int

    def __post_init__(self) -> None:
        try:
            address = ipaddress.ip_address(self.host)
        except ValueError as exc:
            raise ValueError("endpoint host must be a literal IPv4 address") from exc
        if address.version != 4 or not (
            address.is_loopback or any(address in network for network in RFC1918)
        ):
            raise ValueError("endpoint must be loopback or RFC1918 private IPv4")
        if isinstance(self.port, bool) or not isinstance(self.port, int) or not 1 <= self.port <= 65535:
            raise ValueError("endpoint port must be 1..65535")

    @classmethod
    def parse(cls, value: str) -> "PrivateEndpoint":
        if not isinstance(value, str) or value.count(":") != 1:
            raise ValueError("endpoint must use IPv4:port")
        host, raw_port = value.rsplit(":", 1)
        try:
            port = int(raw_port)
        except ValueError as exc:
            raise ValueError("endpoint port must be an integer") from exc
        return cls(host, port)

    def text(self) -> str:
        return f"{self.host}:{self.port}"


@dataclass(frozen=True)
class RelayConfig:
    target: PrivateEndpoint
    listen_port: int = 0
    one_way_delay_ms: float = 0.0
    jitter_ms: float = 0.0
    seed: int = 1
    chunk_bytes: int = DEFAULT_CHUNK_BYTES
    max_buffer_bytes: int = DEFAULT_MAX_BUFFER_BYTES
    disconnect_after_bytes: int | None = None
    disconnect_after_seconds: float | None = None
    connect_timeout_seconds: float = 10.0
    max_connections: int = 1024
    idle_timeout_seconds: float | None = None

    def __post_init__(self) -> None:
        if isinstance(self.listen_port, bool) or not isinstance(self.listen_port, int) or not 0 <= self.listen_port <= 65535:
            raise ValueError("listen_port must be 0..65535")
        for name, value, maximum in (
            ("one_way_delay_ms", self.one_way_delay_ms, 60_000.0),
            ("jitter_ms", self.jitter_ms, 60_000.0),
        ):
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not 0 <= float(value) <= maximum:
                raise ValueError(f"{name} must be between 0 and {maximum:g}")
        if isinstance(self.seed, bool) or not isinstance(self.seed, int):
            raise ValueError("seed must be an integer")
        if isinstance(self.chunk_bytes, bool) or not isinstance(self.chunk_bytes, int) or not 1024 <= self.chunk_bytes <= 1024 * 1024:
            raise ValueError("chunk_bytes must be 1 KiB..1 MiB")
        if (
            isinstance(self.max_buffer_bytes, bool)
            or not isinstance(self.max_buffer_bytes, int)
            or not self.chunk_bytes <= self.max_buffer_bytes <= 256 * 1024 * 1024
        ):
            raise ValueError("max_buffer_bytes must be at least one chunk and <= 256 MiB")
        if self.disconnect_after_bytes is not None and (
            isinstance(self.disconnect_after_bytes, bool)
            or not isinstance(self.disconnect_after_bytes, int)
            or self.disconnect_after_bytes < 1
        ):
            raise ValueError("disconnect_after_bytes must be a positive integer")
        if self.disconnect_after_seconds is not None and (
            isinstance(self.disconnect_after_seconds, bool)
            or not isinstance(self.disconnect_after_seconds, (int, float))
            or self.disconnect_after_seconds <= 0
        ):
            raise ValueError("disconnect_after_seconds must be positive")
        if (
            isinstance(self.connect_timeout_seconds, bool)
            or not isinstance(self.connect_timeout_seconds, (int, float))
            or not 0 < self.connect_timeout_seconds <= 120
        ):
            raise ValueError("connect_timeout_seconds must be >0 and <=120")
        if (
            isinstance(self.max_connections, bool)
            or not isinstance(self.max_connections, int)
            or not 1 <= self.max_connections <= 65536
        ):
            raise ValueError("max_connections must be 1..65536")
        if self.idle_timeout_seconds is not None and (
            isinstance(self.idle_timeout_seconds, bool)
            or not isinstance(self.idle_timeout_seconds, (int, float))
            or not 0 < self.idle_timeout_seconds <= 3600
        ):
            raise ValueError("idle_timeout_seconds must be >0 and <=3600")


@dataclass(frozen=True)
class RelayMetrics:
    schema_version: int
    started_at: str
    connected_at: str | None
    ended_at: str
    listen: str
    target: str
    setup_elapsed_ms: float
    active_elapsed_ms: float
    total_elapsed_ms: float
    configured: dict[str, object]
    traffic: dict[str, int]
    termination: dict[str, object]

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


class _SessionController:
    def __init__(
        self,
        *,
        disconnect_after_bytes: int | None,
        disconnect_after_seconds: float | None,
        max_connections: int,
        idle_timeout_seconds: float | None,
    ):
        self.disconnect_after_bytes = disconnect_after_bytes
        self.disconnect_after_seconds = disconnect_after_seconds
        self.max_connections = max_connections
        self.idle_timeout_seconds = idle_timeout_seconds
        self.stop_event = threading.Event()
        self.lock = threading.Lock()
        self.bytes_by_direction = {"coordinator_to_worker": 0, "worker_to_coordinator": 0}
        self.reason: str | None = None
        self.error_type: str | None = None
        self.error_message: str | None = None
        self.active_sockets: set[socket.socket] = set()
        self.active_connections = 0
        self.connection_count = 0
        self.connected_wall: datetime | None = None
        self.connected_mono: float | None = None
        self.last_activity_mono: float | None = None

    def on_connection_accepted(self, coordinator: socket.socket, worker: socket.socket) -> bool:
        with self.lock:
            if self.stop_event.is_set():
                return False
            if self.connection_count >= self.max_connections:
                return False
            if self.connected_wall is None:
                self.connected_wall = datetime.now(timezone.utc)
                self.connected_mono = time.monotonic()
            self.connection_count += 1
            self.active_connections += 1
            self.active_sockets.add(coordinator)
            self.active_sockets.add(worker)
            self.last_activity_mono = time.monotonic()
            return True

    def on_connection_closed(self, coordinator: socket.socket, worker: socket.socket) -> None:
        with self.lock:
            self.active_sockets.discard(coordinator)
            self.active_sockets.discard(worker)
            self.active_connections = max(0, self.active_connections - 1)
            self.last_activity_mono = time.monotonic()

    def add_forwarded(self, direction: str, count: int) -> None:
        should_stop = False
        with self.lock:
            self.bytes_by_direction[direction] += count
            self.last_activity_mono = time.monotonic()
            if (
                self.disconnect_after_bytes is not None
                and sum(self.bytes_by_direction.values()) >= self.disconnect_after_bytes
                and self.reason is None
            ):
                self.reason = "disconnect_after_bytes"
                should_stop = True
        if should_stop:
            self.stop_event.set()
            self._shutdown_all()

    def fail(self, exc: BaseException) -> None:
        with self.lock:
            if self.reason is None:
                self.reason = "relay_error"
                self.error_type = type(exc).__name__[:128]
                self.error_message = _safe_error_message(exc)
        self.stop_event.set()
        self._shutdown_all()

    def stop(self, reason: str) -> None:
        with self.lock:
            if self.reason is None:
                self.reason = reason
        self.stop_event.set()
        self._shutdown_all()

    def _shutdown_all(self) -> None:
        with self.lock:
            socks = list(self.active_sockets)
        for sock in socks:
            try:
                sock.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass


def _safe_error_message(exc: BaseException) -> str:
    errno = getattr(exc, "errno", None)
    if isinstance(errno, int):
        return f"errno={errno}"
    return type(exc).__name__[:128]


def _iso(value: datetime) -> str:
    return value.isoformat().replace("+00:00", "Z")


def _put_with_stop(items: queue.Queue, value: object, stop_event: threading.Event) -> bool:
    while not stop_event.is_set():
        try:
            items.put(value, timeout=0.1)
            return True
        except queue.Full:
            continue
    return False


def _is_disconnect_error(exc: BaseException) -> bool:
    if isinstance(exc, (ConnectionResetError, BrokenPipeError, ConnectionAbortedError)):
        return True
    if isinstance(exc, OSError):
        if getattr(exc, "winerror", None) in (10054, 10053, 10058):
            return True
        if getattr(exc, "errno", None) in (104, 32, 103):
            return True
    return False


def _receiver(
    source: socket.socket,
    items: queue.Queue,
    *,
    config: RelayConfig,
    rng: random.Random,
    controller: _SessionController,
) -> None:
    last_ready = 0.0
    try:
        while not controller.stop_event.is_set():
            data = source.recv(config.chunk_bytes)
            if not data:
                _put_with_stop(items, _SENTINEL, controller.stop_event)
                return
            variation = rng.uniform(-config.jitter_ms, config.jitter_ms) if config.jitter_ms else 0.0
            delay_seconds = max(0.0, (config.one_way_delay_ms + variation) / 1000.0)
            ready_at = max(last_ready, time.monotonic() + delay_seconds)
            last_ready = ready_at
            if not _put_with_stop(items, (ready_at, data), controller.stop_event):
                return
    except OSError as exc:
        if _is_disconnect_error(exc):
            _put_with_stop(items, _SENTINEL, controller.stop_event)
            return
        if not controller.stop_event.is_set():
            controller.fail(exc)


def _sender(
    destination: socket.socket,
    items: queue.Queue,
    *,
    direction: str,
    controller: _SessionController,
    finished: threading.Event,
) -> None:
    try:
        while not controller.stop_event.is_set():
            try:
                item = items.get(timeout=0.1)
            except queue.Empty:
                continue
            if item is _SENTINEL:
                try:
                    destination.shutdown(socket.SHUT_WR)
                except OSError:
                    pass
                return
            ready_at, data = item
            remaining = ready_at - time.monotonic()
            if remaining > 0 and controller.stop_event.wait(remaining):
                return
            destination.sendall(data)
            controller.add_forwarded(direction, len(data))
    except OSError as exc:
        if _is_disconnect_error(exc):
            return
        if not controller.stop_event.is_set():
            controller.fail(exc)
    finally:
        finished.set()


def _build_metrics(
    config: RelayConfig,
    *,
    actual_endpoint: PrivateEndpoint,
    started_wall: datetime,
    started_mono: float,
    connected_wall: datetime | None,
    connected_mono: float | None,
    traffic: dict[str, int],
    connection_count: int,
    reason: str,
    error_type: str | None,
    error_message: str | None,
) -> RelayMetrics:
    ended_wall = datetime.now(timezone.utc)
    ended_mono = time.monotonic()
    total_elapsed_ms = max(0.0, (ended_mono - started_mono) * 1000.0)
    if connected_mono is None:
        setup_elapsed_ms = total_elapsed_ms
        active_elapsed_ms = 0.0
    else:
        setup_elapsed_ms = max(0.0, (connected_mono - started_mono) * 1000.0)
        active_elapsed_ms = max(0.0, (ended_mono - connected_mono) * 1000.0)
    total = traffic.get("coordinator_to_worker", 0) + traffic.get("worker_to_coordinator", 0)
    return RelayMetrics(
        schema_version=1,
        started_at=_iso(started_wall),
        connected_at=_iso(connected_wall) if connected_wall is not None else None,
        ended_at=_iso(ended_wall),
        listen=actual_endpoint.text(),
        target=config.target.text(),
        setup_elapsed_ms=setup_elapsed_ms,
        active_elapsed_ms=active_elapsed_ms,
        total_elapsed_ms=total_elapsed_ms,
        configured={
            "one_way_delay_ms": float(config.one_way_delay_ms),
            "jitter_ms": float(config.jitter_ms),
            "seed": config.seed,
            "chunk_bytes": config.chunk_bytes,
            "max_buffer_bytes": config.max_buffer_bytes,
            "disconnect_after_bytes": config.disconnect_after_bytes,
            "disconnect_after_seconds": config.disconnect_after_seconds,
            "connect_timeout_seconds": float(config.connect_timeout_seconds),
            "max_connections": config.max_connections,
            "idle_timeout_seconds": config.idle_timeout_seconds,
        },
        traffic={
            "coordinator_to_worker_bytes": traffic.get("coordinator_to_worker", 0),
            "worker_to_coordinator_bytes": traffic.get("worker_to_coordinator", 0),
            "total_forwarded_bytes": total,
            "connection_count": connection_count,
        },
        termination={
            "reason": reason,
            "error_type": error_type,
            "message": error_message,
        },
    )


def _persist_metrics(metrics: RelayMetrics, metrics_path: Path | None) -> None:
    if metrics_path is None:
        return
    metrics_path.parent.mkdir(parents=True, exist_ok=True)
    metrics_path.write_text(
        json.dumps(metrics.to_dict(), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _handle_connection(
    coordinator: socket.socket,
    worker: socket.socket,
    *,
    config: RelayConfig,
    controller: _SessionController,
    seed_offset: int,
) -> None:
    try:
        worker.settimeout(None)
        coordinator.settimeout(None)
        queue_slots = max(1, config.max_buffer_bytes // config.chunk_bytes)
        forward: queue.Queue = queue.Queue(maxsize=queue_slots)
        reverse: queue.Queue = queue.Queue(maxsize=queue_slots)
        forward_done = threading.Event()
        reverse_done = threading.Event()
        threads = (
            threading.Thread(
                target=_receiver,
                args=(coordinator, forward),
                kwargs={"config": config, "rng": random.Random(config.seed + seed_offset), "controller": controller},
                daemon=True,
            ),
            threading.Thread(
                target=_sender,
                args=(worker, forward),
                kwargs={"direction": "coordinator_to_worker", "controller": controller, "finished": forward_done},
                daemon=True,
            ),
            threading.Thread(
                target=_receiver,
                args=(worker, reverse),
                kwargs={"config": config, "rng": random.Random((config.seed + seed_offset) ^ 0x5EED), "controller": controller},
                daemon=True,
            ),
            threading.Thread(
                target=_sender,
                args=(coordinator, reverse),
                kwargs={"direction": "worker_to_coordinator", "controller": controller, "finished": reverse_done},
                daemon=True,
            ),
        )
        for thread in threads:
            thread.start()

        while not controller.stop_event.is_set() and not (forward_done.is_set() and reverse_done.is_set()):
            time.sleep(0.01)
        for thread in threads:
            thread.join(timeout=2.0)
    finally:
        controller.on_connection_closed(coordinator, worker)
        for sock in (coordinator, worker):
            try:
                sock.close()
            except OSError:
                pass


def run_relay(
    config: RelayConfig,
    *,
    on_ready: Callable[[PrivateEndpoint], None] | None = None,
    metrics_path: Path | None = None,
    stop_event: threading.Event | None = None,
) -> RelayMetrics:
    """Relay TCP connections and return content-free traffic metrics."""
    started_wall = datetime.now(timezone.utc)
    started_mono = time.monotonic()
    controller = _SessionController(
        disconnect_after_bytes=config.disconnect_after_bytes,
        disconnect_after_seconds=config.disconnect_after_seconds,
        max_connections=config.max_connections,
        idle_timeout_seconds=config.idle_timeout_seconds,
    )
    if stop_event is not None:
        def _watch_stop():
            stop_event.wait()
            controller.stop("eof")
        threading.Thread(target=_watch_stop, daemon=True).start()

    conn_threads: list[threading.Thread] = []

    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
        listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        listener.bind(("127.0.0.1", config.listen_port))
        listener.listen(128)
        listener.settimeout(0.1)
        actual_endpoint = PrivateEndpoint("127.0.0.1", listener.getsockname()[1])
        if on_ready is not None:
            on_ready(actual_endpoint)

        while not controller.stop_event.is_set():
            if config.disconnect_after_seconds is not None and controller.connected_mono is not None:
                if time.monotonic() >= controller.connected_mono + float(config.disconnect_after_seconds):
                    controller.stop("disconnect_after_seconds")
                    break

            with controller.lock:
                active_count = controller.active_connections
                total_accepted = controller.connection_count
                last_active = controller.last_activity_mono

            if config.max_connections == 1 and total_accepted >= 1 and active_count == 0:
                controller.stop("eof")
                break

            if total_accepted >= config.max_connections and active_count == 0:
                controller.stop("eof")
                break

            if (
                config.idle_timeout_seconds is not None
                and total_accepted > 0
                and active_count == 0
                and last_active is not None
                and (time.monotonic() - last_active) >= config.idle_timeout_seconds
            ):
                controller.stop("eof")
                break

            try:
                coordinator, _ = listener.accept()
            except socket.timeout:
                continue
            except OSError:
                break

            try:
                worker = socket.create_connection(
                    (config.target.host, config.target.port),
                    timeout=float(config.connect_timeout_seconds),
                )
            except OSError as exc:
                try:
                    coordinator.close()
                except OSError:
                    pass
                with controller.lock:
                    first_conn = controller.connection_count == 0
                if first_conn:
                    metrics = _build_metrics(
                        config,
                        actual_endpoint=actual_endpoint,
                        started_wall=started_wall,
                        started_mono=started_mono,
                        connected_wall=None,
                        connected_mono=None,
                        traffic={"coordinator_to_worker": 0, "worker_to_coordinator": 0},
                        connection_count=0,
                        reason="connect_error",
                        error_type=type(exc).__name__[:128],
                        error_message=_safe_error_message(exc),
                    )
                    _persist_metrics(metrics, metrics_path)
                    return metrics
                else:
                    controller.fail(exc)
                    break

            accepted = controller.on_connection_accepted(coordinator, worker)
            if not accepted:
                try:
                    coordinator.close()
                    worker.close()
                except OSError:
                    pass
                break

            offset = controller.connection_count * 17
            thread = threading.Thread(
                target=_handle_connection,
                args=(coordinator, worker),
                kwargs={"config": config, "controller": controller, "seed_offset": offset},
                daemon=True,
            )
            thread.start()
            conn_threads.append(thread)

    for thread in conn_threads:
        thread.join(timeout=2.0)

    with controller.lock:
        reason = controller.reason or "eof"
        error_type = controller.error_type
        error_message = controller.error_message
        traffic = dict(controller.bytes_by_direction)
        connected_wall = controller.connected_wall
        connected_mono = controller.connected_mono
        conn_count = controller.connection_count

    metrics = _build_metrics(
        config,
        actual_endpoint=actual_endpoint,
        started_wall=started_wall,
        started_mono=started_mono,
        connected_wall=connected_wall,
        connected_mono=connected_mono,
        traffic=traffic,
        connection_count=conn_count,
        reason=reason,
        error_type=error_type,
        error_message=error_message,
    )
    _persist_metrics(metrics, metrics_path)
    return metrics


def run_relay_once(
    config: RelayConfig,
    *,
    on_ready: Callable[[PrivateEndpoint], None] | None = None,
    metrics_path: Path | None = None,
) -> RelayMetrics:
    """Relay one TCP connection and return content-free traffic metrics."""
    return run_relay(replace(config, max_connections=1), on_ready=on_ready, metrics_path=metrics_path)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="ComputeMesh bounded TCP measurement relay")
    parser.add_argument("--target", required=True, type=PrivateEndpoint.parse)
    parser.add_argument("--listen-port", type=int, default=50053)
    parser.add_argument("--delay-ms", type=float, default=0.0)
    parser.add_argument("--jitter-ms", type=float, default=0.0)
    parser.add_argument("--seed", type=int, default=1)
    parser.add_argument("--chunk-bytes", type=int, default=DEFAULT_CHUNK_BYTES)
    parser.add_argument("--max-buffer-bytes", type=int, default=DEFAULT_MAX_BUFFER_BYTES)
    parser.add_argument("--disconnect-after-bytes", type=int)
    parser.add_argument("--disconnect-after-seconds", type=float)
    parser.add_argument("--connect-timeout", type=float, default=10.0)
    parser.add_argument("--max-connections", type=int, default=1024)
    parser.add_argument("--idle-timeout", type=float, default=2.0)
    parser.add_argument("--metrics", type=Path, required=True)
    args = parser.parse_args(argv)
    config = RelayConfig(
        target=args.target,
        listen_port=args.listen_port,
        one_way_delay_ms=args.delay_ms,
        jitter_ms=args.jitter_ms,
        seed=args.seed,
        chunk_bytes=args.chunk_bytes,
        max_buffer_bytes=args.max_buffer_bytes,
        disconnect_after_bytes=args.disconnect_after_bytes,
        disconnect_after_seconds=args.disconnect_after_seconds,
        connect_timeout_seconds=args.connect_timeout,
        max_connections=args.max_connections,
        idle_timeout_seconds=args.idle_timeout,
    )

    def announce(endpoint: PrivateEndpoint) -> None:
        print(f"READY {endpoint.text()} -> {config.target.text()}", flush=True)

    try:
        metrics = run_relay(config, on_ready=announce, metrics_path=args.metrics)
    except KeyboardInterrupt:
        return 130
    except Exception as exc:
        print(f"relay failed: {type(exc).__name__}", flush=True)
        return 2
    print(json.dumps(metrics.to_dict(), sort_keys=True))
    return 0 if metrics.termination["reason"] == "eof" else 3


if __name__ == "__main__":
    raise SystemExit(main())
