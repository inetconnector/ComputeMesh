#!/usr/bin/env python3
"""Bounded loopback TCP relay for M1 runtime measurement experiments.

This is a lab instrument, not a ComputeMesh transport. It can count forwarded
bytes, delay stream chunks, add bounded deterministic jitter, and force a
connection drop. It never inspects or persists payload contents.
"""
from __future__ import annotations

import argparse
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import ipaddress
import json
from pathlib import Path
import queue
import random
import socket
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
        if isinstance(self.max_buffer_bytes, bool) or not isinstance(self.max_buffer_bytes, int) or not self.chunk_bytes <= self.max_buffer_bytes <= 256 * 1024 * 1024:
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
        if isinstance(self.connect_timeout_seconds, bool) or not isinstance(self.connect_timeout_seconds, (int, float)) or not 0 < self.connect_timeout_seconds <= 120:
            raise ValueError("connect_timeout_seconds must be >0 and <=120")


@dataclass(frozen=True)
class RelayMetrics:
    schema_version: int
    started_at: str
    ended_at: str
    listen: str
    target: str
    elapsed_ms: float
    configured: dict[str, object]
    traffic: dict[str, int]
    termination: dict[str, object]

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


class _Controller:
    def __init__(self, sockets: tuple[socket.socket, ...], disconnect_after_bytes: int | None):
        self.sockets = sockets
        self.disconnect_after_bytes = disconnect_after_bytes
        self.stop_event = threading.Event()
        self.lock = threading.Lock()
        self.bytes_by_direction = {"coordinator_to_worker": 0, "worker_to_coordinator": 0}
        self.reason: str | None = None
        self.error_type: str | None = None
        self.error_message: str | None = None

    def add_forwarded(self, direction: str, count: int) -> None:
        should_stop = False
        with self.lock:
            self.bytes_by_direction[direction] += count
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
                self.reason = "error"
                self.error_type = type(exc).__name__[:128]
                self.error_message = (str(exc) or type(exc).__name__)[:1024]
        self.stop_event.set()
        self._shutdown_all()

    def stop(self, reason: str) -> None:
        with self.lock:
            if self.reason is None:
                self.reason = reason
        self.stop_event.set()
        self._shutdown_all()

    def _shutdown_all(self) -> None:
        for sock in self.sockets:
            try:
                sock.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass


def _put_with_stop(items: queue.Queue, value: object, stop_event: threading.Event) -> bool:
    while not stop_event.is_set():
        try:
            items.put(value, timeout=0.1)
            return True
        except queue.Full:
            continue
    return False


def _receiver(
    source: socket.socket,
    items: queue.Queue,
    *,
    config: RelayConfig,
    rng: random.Random,
    controller: _Controller,
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
            candidate = time.monotonic() + delay_seconds
            ready_at = max(last_ready, candidate)
            last_ready = ready_at
            if not _put_with_stop(items, (ready_at, data), controller.stop_event):
                return
    except OSError as exc:
        if not controller.stop_event.is_set():
            controller.fail(exc)


def _sender(
    destination: socket.socket,
    items: queue.Queue,
    *,
    direction: str,
    controller: _Controller,
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
                finished.set()
                return
            ready_at, data = item
            remaining = ready_at - time.monotonic()
            if remaining > 0 and controller.stop_event.wait(remaining):
                return
            destination.sendall(data)
            controller.add_forwarded(direction, len(data))
    except OSError as exc:
        if not controller.stop_event.is_set():
            controller.fail(exc)
    finally:
        finished.set()


def run_relay_once(
    config: RelayConfig,
    *,
    on_ready: Callable[[PrivateEndpoint], None] | None = None,
    metrics_path: Path | None = None,
) -> RelayMetrics:
    """Relay one TCP connection and return content-free traffic metrics."""
    started_wall = datetime.now(timezone.utc)
    started_mono = time.monotonic()
    reason = "eof"
    error_type = None
    error_message = None
    coordinator: socket.socket | None = None
    worker: socket.socket | None = None

    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
        listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        listener.bind(("127.0.0.1", config.listen_port))
        listener.listen(1)
        actual_endpoint = PrivateEndpoint("127.0.0.1", listener.getsockname()[1])
        if on_ready is not None:
            on_ready(actual_endpoint)
        coordinator, _ = listener.accept()

    try:
        worker = socket.create_connection(
            (config.target.host, config.target.port),
            timeout=float(config.connect_timeout_seconds),
        )
        worker.settimeout(None)
        coordinator.settimeout(None)
        connected_mono = time.monotonic()
        sockets = (coordinator, worker)
        controller = _Controller(sockets, config.disconnect_after_bytes)
        queue_slots = max(1, config.max_buffer_bytes // config.chunk_bytes)
        forward: queue.Queue = queue.Queue(maxsize=queue_slots)
        reverse: queue.Queue = queue.Queue(maxsize=queue_slots)
        forward_done = threading.Event()
        reverse_done = threading.Event()
        threads = (
            threading.Thread(
                target=_receiver,
                args=(coordinator, forward),
                kwargs={"config": config, "rng": random.Random(config.seed), "controller": controller},
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
                kwargs={"config": config, "rng": random.Random(config.seed ^ 0x5EED), "controller": controller},
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

        deadline = (
            connected_mono + float(config.disconnect_after_seconds)
            if config.disconnect_after_seconds is not None
            else None
        )
        while not controller.stop_event.is_set() and not (forward_done.is_set() and reverse_done.is_set()):
            if deadline is not None and time.monotonic() >= deadline:
                controller.stop("disconnect_after_seconds")
                break
            time.sleep(0.01)
        if not controller.stop_event.is_set() and forward_done.is_set() and reverse_done.is_set():
            controller.stop("eof")
        for thread in threads:
            thread.join(timeout=2.0)
        with controller.lock:
            reason = controller.reason or "eof"
            error_type = controller.error_type
            error_message = controller.error_message
            traffic = dict(controller.bytes_by_direction)
    except Exception as exc:
        reason = "error"
        error_type = type(exc).__name__[:128]
        error_message = (str(exc) or type(exc).__name__)[:1024]
        traffic = {"coordinator_to_worker": 0, "worker_to_coordinator": 0}
        raise
    finally:
        for sock in (coordinator, worker):
            if sock is not None:
                try:
                    sock.close()
                except OSError:
                    pass
        ended_wall = datetime.now(timezone.utc)
        elapsed_ms = (time.monotonic() - started_mono) * 1000.0
        total = traffic.get("coordinator_to_worker", 0) + traffic.get("worker_to_coordinator", 0)
        metrics = RelayMetrics(
            schema_version=1,
            started_at=started_wall.isoformat().replace("+00:00", "Z"),
            ended_at=ended_wall.isoformat().replace("+00:00", "Z"),
            listen=actual_endpoint.text(),
            target=config.target.text(),
            elapsed_ms=elapsed_ms,
            configured={
                "one_way_delay_ms": float(config.one_way_delay_ms),
                "jitter_ms": float(config.jitter_ms),
                "seed": config.seed,
                "chunk_bytes": config.chunk_bytes,
                "max_buffer_bytes": config.max_buffer_bytes,
                "disconnect_after_bytes": config.disconnect_after_bytes,
                "disconnect_after_seconds": config.disconnect_after_seconds,
            },
            traffic={
                "coordinator_to_worker_bytes": traffic.get("coordinator_to_worker", 0),
                "worker_to_coordinator_bytes": traffic.get("worker_to_coordinator", 0),
                "total_forwarded_bytes": total,
            },
            termination={
                "reason": reason,
                "error_type": error_type,
                "message": error_message,
            },
        )
        if metrics_path is not None:
            metrics_path.parent.mkdir(parents=True, exist_ok=True)
            metrics_path.write_text(
                json.dumps(metrics.to_dict(), indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )
    return metrics


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
    )

    def announce(endpoint: PrivateEndpoint) -> None:
        print(f"READY {endpoint.text()} -> {config.target.text()}", flush=True)

    try:
        metrics = run_relay_once(config, on_ready=announce, metrics_path=args.metrics)
    except KeyboardInterrupt:
        return 130
    except Exception as exc:
        print(f"relay failed: {type(exc).__name__}: {exc}", flush=True)
        return 2
    print(json.dumps(metrics.to_dict(), sort_keys=True))
    return 0 if metrics.termination["reason"] == "eof" else 3


if __name__ == "__main__":
    raise SystemExit(main())
