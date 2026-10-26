"""Run the existing authenticated dashboard relay after NodeOS preflight."""
from __future__ import annotations

from contextlib import contextmanager
import os
from pathlib import Path
import signal
import sys
import threading
from typing import Iterator

from services.appliance_dashboard.tunnel_relay import (
    nodeos_provider_ready,
    start_cloud_tunnel_relay,
)
from tools.appliance.node_identity import NodeIdentityError, resolve_node_id


class HeartbeatIdentityUnavailable(RuntimeError):
    """Raised when the dedicated relay cannot load the enrolled identity."""


# Kept as a compatibility alias for callers that imported the old private
# helper exception; lock contention itself is reported as a boolean.
RelayAlreadyRunning = HeartbeatIdentityUnavailable


def load_heartbeat_node_id() -> str:
    """Load the enrolled ID used by the dedicated heartbeat service."""
    try:
        return resolve_node_id(require_enrolled=True)
    except NodeIdentityError as exc:
        raise HeartbeatIdentityUnavailable(str(exc)) from exc


@contextmanager
def _relay_process_lock() -> Iterator[bool]:
    """Keep dashboard and manually started relay processes single-owner."""
    configured = os.environ.get("COMPUTEMESH_HEARTBEAT_LOCK_PATH", "").strip()
    lock_path = Path(configured) if configured else (
        # The heartbeat unit runs as ``computemesh`` and the builder grants
        # that user write access to /var/lib/computemesh.  /run is owned by
        # root unless a separate RuntimeDirectory unit is configured.
        Path("/var/lib/computemesh/node-heartbeat.lock")
        if os.name != "nt" and os.environ.get("COMPUTEMESH_NODEOS", "").strip()
        else Path(os.environ.get("TEMP", ".")) / "computemesh-node-heartbeat.lock"
    )
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    handle = lock_path.open("a+", encoding="ascii")
    acquired = False
    try:
        if os.name == "nt":
            import msvcrt

            handle.seek(0, os.SEEK_END)
            if handle.tell() == 0:
                handle.write("0")
                handle.flush()
            handle.seek(0)
            try:
                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
                acquired = True
            except OSError:
                acquired = False
        else:
            import fcntl

            try:
                fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                acquired = True
            except OSError:
                acquired = False
        yield acquired
    finally:
        if acquired:
            try:
                if os.name == "nt":
                    import msvcrt

                    handle.seek(0)
                    msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
                else:
                    import fcntl

                    fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
            except OSError:
                pass
        handle.close()


def main() -> int:
    if not nodeos_provider_ready():
        print("NodeOS heartbeat relay refused: provider preflight is not ready", file=sys.stderr)
        return 1
    try:
        node_id = load_heartbeat_node_id()
    except HeartbeatIdentityUnavailable as exc:
        print(f"NodeOS heartbeat relay refused: {exc}", file=sys.stderr)
        return 1
    with _relay_process_lock() as acquired:
        if not acquired:
            print("NodeOS heartbeat relay already has an active owner", file=sys.stderr)
            return 0
        relay = start_cloud_tunnel_relay(node_id=node_id)
        stop_event = threading.Event()

        def stop(_signum: int, _frame: object) -> None:
            stop_event.set()
            relay.stop()

        for name in ("SIGTERM", "SIGINT"):
            signum = getattr(signal, name, None)
            if signum is not None:
                signal.signal(signum, stop)
        try:
            while not stop_event.wait(1.0):
                pass
        finally:
            relay.stop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
