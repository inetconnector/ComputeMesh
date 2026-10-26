"""Run the existing authenticated dashboard relay after NodeOS preflight."""
from __future__ import annotations

import signal
import sys
import threading

from services.appliance_dashboard.tunnel_relay import (
    nodeos_provider_ready,
    start_cloud_tunnel_relay,
)


def main() -> int:
    if not nodeos_provider_ready():
        print("NodeOS heartbeat relay refused: provider preflight is not ready", file=sys.stderr)
        return 1
    relay = start_cloud_tunnel_relay()
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
