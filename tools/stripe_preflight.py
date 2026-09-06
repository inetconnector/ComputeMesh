"""Secret-free preflight for the deployed Stripe Checkout/Connect boundary.

This command checks local environment shape and the gateway's non-sensitive
``/healthz`` response. It never creates a Checkout Session, connected account,
transfer, or webhook event, and it never prints secret values.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys
from typing import Any
import urllib.error
import urllib.request


def _mode_from_key(value: str) -> str:
    key = value.strip()
    if key.startswith("sk_live_"):
        return "live"
    if key.startswith("sk_test_"):
        return "test"
    return "unconfigured"


def evaluate_environment(env: dict[str, str]) -> dict[str, Any]:
    """Return non-sensitive configuration checks for a Stripe runtime."""
    mode = _mode_from_key(env.get("STRIPE_API_KEY", ""))
    webhook_secrets = [
        item.strip()
        for item in (env.get("COMPUTEMESH_STRIPE_WEBHOOK_SECRETS", "") or env.get("STRIPE_WEBHOOK_SECRET", "")).split(",")
        if item.strip()
    ]
    session_store = (env.get("COMPUTEMESH_STRIPE_SESSION_STORE_PATH", "").strip()
                     or env.get("COMPUTEMESH_STRIPE_SESSION_STORE", "").strip())
    checks = {
        "api_key_configured": mode != "unconfigured",
        "mode": mode,
        "webhook_secret_configured": bool(webhook_secrets) and all(item.startswith("whsec_") for item in webhook_secrets),
        "session_store_configured": bool(session_store),
        "session_store_parent_ready": bool(session_store) and Path(session_store).expanduser().parent.is_dir(),
    }
    checks["configuration_ready"] = all(
        checks[name]
        for name in (
            "api_key_configured",
            "webhook_secret_configured",
            "session_store_configured",
            "session_store_parent_ready",
        )
    )
    return checks


def fetch_health(url: str, timeout: float = 10.0) -> dict[str, Any]:
    """Fetch and validate the gateway's secret-free health document."""
    endpoint = url.rstrip("/") + "/healthz"
    request = urllib.request.Request(endpoint, headers={"Accept": "application/json"})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            status_code = int(response.status)
            payload = json.loads(response.read().decode("utf-8"))
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        return {"reachable": False, "error": type(exc).__name__}
    if not isinstance(payload, dict):
        return {"reachable": True, "http_status": status_code, "healthy": False, "error": "invalid_json_object"}
    stripe = payload.get("stripe") if isinstance(payload.get("stripe"), dict) else {}
    healthy = (
        status_code == 200
        and payload.get("status") == "healthy"
        and stripe.get("status") == "ready"
        and stripe.get("checkout_configured") is True
        and stripe.get("webhook_configured") is True
        and stripe.get("session_store_configured") is True
    )
    return {
        "reachable": True,
        "http_status": status_code,
        "healthy": healthy,
        "gateway_status": payload.get("status"),
        "stripe": {
            "status": stripe.get("status"),
            "mode": stripe.get("mode"),
            "checkout_configured": stripe.get("checkout_configured") is True,
            "webhook_configured": stripe.get("webhook_configured") is True,
            "session_store_configured": stripe.get("session_store_configured") is True,
        },
    }


def overall_ready(environment: dict[str, Any], health: dict[str, Any], *, require_local_config: bool) -> bool:
    """Combine local configuration and deployed health without exposing secrets."""
    return health.get("healthy") is True and (
        environment.get("configuration_ready") is True or not require_local_config
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", default=os.environ.get("COMPUTEMESH_PUBLIC_BASE_URL", "https://mesh.inetconnector.com"))
    parser.add_argument(
        "--require-local-config",
        action="store_true",
        help="fail unless this shell also contains the Stripe runtime configuration",
    )
    args = parser.parse_args(argv)
    environment = evaluate_environment(dict(os.environ))
    health = fetch_health(args.url)
    result = {"configuration": environment, "health": health}
    result["configuration_scope"] = "local_required" if args.require_local_config else "deployed_gateway"
    result["ready"] = overall_ready(environment, health, require_local_config=args.require_local_config)
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if result["ready"] else 1


if __name__ == "__main__":
    sys.exit(main())
