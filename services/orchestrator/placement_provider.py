"""Placement boundary between public ComputeMesh runtime code and placement policy.

The public repository owns the interoperability contract, not the production
placement implementation. Production deployments should use a remote provider
backed by the private ComputeMesh control plane. The local provider exists only
for the disclosed M1/reference scheduler and reproducible research.
"""
from __future__ import annotations

from dataclasses import dataclass
import json
from typing import Any, Protocol
from urllib import error as urlerror
from urllib import request as urlrequest

from services.scheduler.placement import build_placement_decision


class PlacementProviderError(RuntimeError):
    pass


class PlacementProvider(Protocol):
    def decide(self, **inputs: Any) -> dict[str, Any]:
        ...


@dataclass(frozen=True)
class ReferencePlacementProvider:
    """Disclosed reference/M1 planner; not the production ComputeMesh scheduler."""

    def decide(self, **inputs: Any) -> dict[str, Any]:
        return build_placement_decision(**inputs)


@dataclass(frozen=True)
class RemotePlacementProvider:
    """Thin client for the private production control plane.

    The API returns only the externally required placement decision. Internal
    scores, candidate rankings, model features and pricing/reputation state are
    intentionally unavailable to this client.
    """

    endpoint: str
    bearer_token: str
    timeout_seconds: float = 10.0

    def __post_init__(self) -> None:
        if not self.endpoint.startswith("https://"):
            raise ValueError("production placement endpoint must use HTTPS")
        if not self.bearer_token:
            raise ValueError("placement bearer token must be non-empty")
        if not 0 < self.timeout_seconds <= 60:
            raise ValueError("timeout_seconds must be within (0,60]")

    def decide(self, **inputs: Any) -> dict[str, Any]:
        body = json.dumps(inputs, sort_keys=True, separators=(",", ":")).encode("utf-8")
        req = urlrequest.Request(
            self.endpoint,
            data=body,
            method="POST",
            headers={
                "Authorization": f"Bearer {self.bearer_token}",
                "Content-Type": "application/json",
                "Accept": "application/json",
            },
        )
        try:
            with urlrequest.urlopen(req, timeout=self.timeout_seconds) as response:
                raw = response.read(2 * 1024 * 1024 + 1)
        except (urlerror.URLError, TimeoutError) as exc:
            raise PlacementProviderError("private placement service is unavailable") from exc
        if len(raw) > 2 * 1024 * 1024:
            raise PlacementProviderError("private placement response exceeded 2 MiB")
        try:
            value = json.loads(raw.decode("utf-8"))
        except (UnicodeError, json.JSONDecodeError) as exc:
            raise PlacementProviderError("private placement service returned invalid JSON") from exc
        if not isinstance(value, dict):
            raise PlacementProviderError("private placement response must be an object")
        return value
