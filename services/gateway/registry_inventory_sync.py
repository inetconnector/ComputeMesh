"""Minimized public-to-private model inventory synchronization."""

from __future__ import annotations

import json
import os
from typing import Any
from urllib import error, request


def sync_model_inventory(*, node_id: str, models: list[dict[str, Any]]) -> bool:
    """Send only safe serving metadata to the configured private registry."""
    url = os.environ.get("COMPUTEMESH_PRIVATE_REGISTRY_RECONCILE_URL", "").strip()
    token = os.environ.get("COMPUTEMESH_INTERNAL_BEARER_TOKEN", "").strip()
    if not url or not token:
        return False
    payload = json.dumps(
        {"node_id": node_id, "models": models, "ttl_seconds": 180},
        separators=(",", ":"),
    ).encode("utf-8")
    req = request.Request(
        url,
        data=payload,
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        },
        method="POST",
    )
    try:
        with request.urlopen(req, timeout=2.0) as response:
            return response.status == 200
    except (OSError, error.URLError, TimeoutError):
        return False


__all__ = ["sync_model_inventory"]
