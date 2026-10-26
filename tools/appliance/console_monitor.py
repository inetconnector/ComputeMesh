"""Small, secret-free tty1 status monitor for the NodeOS appliance."""
from __future__ import annotations

import argparse
import json
import subprocess
import time
from urllib.error import URLError
from urllib.request import urlopen


def _unit_state(unit: str) -> str:
    try:
        result = subprocess.run(
            ["systemctl", "is-active", unit],
            capture_output=True,
            text=True,
            timeout=2,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return "unknown"
    return result.stdout.strip() or "unknown"


def read_status(url: str = "http://127.0.0.1:8080/api/status") -> dict[str, object]:
    """Read only the loopback status endpoint; never print response secrets."""
    try:
        with urlopen(url, timeout=2) as response:  # noqa: S310 - fixed loopback default
            payload = json.loads(response.read(128 * 1024).decode("utf-8"))
        if not isinstance(payload, dict):
            return {"state": "invalid"}
        return {
            "state": str(payload.get("status") or payload.get("state") or "unknown"),
            "model": str(payload.get("model") or payload.get("model_id") or "none"),
        }
    except (OSError, URLError, ValueError, UnicodeError):
        return {"state": "unreachable", "model": "unknown"}


def render_status() -> str:
    status = read_status()
    return (
        "ComputeMesh NodeOS\n"
        f"  appliance: {_unit_state('computemesh-appliance.service')}\n"
        f"  provider:  {_unit_state('computemesh-node.service')}\n"
        f"  inference: {status.get('state', 'unknown')}\n"
        f"  model:     {status.get('model', 'unknown')}\n"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--interval", type=float, default=5.0)
    parser.add_argument("--once", action="store_true")
    args = parser.parse_args(argv)
    if args.interval <= 0:
        parser.error("--interval must be positive")
    while True:
        print("\033[2J\033[H" + render_status(), end="", flush=True)
        if args.once:
            return 0
        time.sleep(args.interval)


if __name__ == "__main__":
    raise SystemExit(main())
