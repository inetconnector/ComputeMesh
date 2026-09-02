"""Fail-closed client for the live-session GPU promo dispatcher."""
from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlparse

_MAX_RESPONSE_BYTES = 512 * 1024


class GpuPromoDispatchClientError(RuntimeError):
    def __init__(self, message: str, *, status_code: int | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code


@dataclass(frozen=True)
class GpuPromoDispatchClient:
    base_url: str
    bearer_token: str
    timeout_seconds: float = 305.0

    def __post_init__(self) -> None:
        parsed = urlparse(self.base_url)
        if parsed.scheme != "http" or parsed.hostname not in {"127.0.0.1", "localhost", "::1"}:
            raise ValueError("GPU promo dispatch URL must use loopback HTTP")
        if parsed.path not in {"", "/"} or parsed.query or parsed.fragment:
            raise ValueError("GPU promo dispatch URL must not include path/query/fragment")
        if len(self.bearer_token.strip()) < 24:
            raise ValueError("GPU promo dispatch token must be at least 24 characters")
        if self.timeout_seconds <= 0 or self.timeout_seconds > 310:
            raise ValueError("GPU promo dispatch timeout must be in (0,310] seconds")

    def dispatch(self, *, node_id: str, challenge: dict[str, Any]) -> dict[str, Any]:
        raw = json.dumps(
            {"node_id": node_id, "challenge": challenge},
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        request = urllib.request.Request(
            self.base_url.rstrip("/") + "/internal/v1/promo/gpu-dispatch",
            data=raw,
            headers={
                "Authorization": f"Bearer {self.bearer_token}",
                "Content-Type": "application/json",
                "Accept": "application/json",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout_seconds) as response:
                payload = response.read(_MAX_RESPONSE_BYTES + 1)
                if len(payload) > _MAX_RESPONSE_BYTES:
                    raise GpuPromoDispatchClientError("GPU promo dispatch response is too large")
                if int(response.status) != 200:
                    raise GpuPromoDispatchClientError(
                        "GPU promo dispatch returned an unexpected status",
                        status_code=int(response.status),
                    )
        except urllib.error.HTTPError as exc:
            try:
                exc.read(_MAX_RESPONSE_BYTES + 1)
            except Exception:
                pass
            raise GpuPromoDispatchClientError(
                "GPU promo dispatch rejected the request",
                status_code=int(exc.code),
            ) from exc
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            raise GpuPromoDispatchClientError("GPU promo dispatch is unavailable") from exc

        try:
            value = json.loads(payload.decode("utf-8"))
        except (UnicodeError, json.JSONDecodeError) as exc:
            raise GpuPromoDispatchClientError("GPU promo dispatch returned invalid JSON") from exc
        if not isinstance(value, dict):
            raise GpuPromoDispatchClientError("GPU promo dispatch response must be an object")
        return value


def build_gpu_promo_dispatch_client_from_env() -> GpuPromoDispatchClient:
    base_url = os.environ.get("COMPUTEMESH_GPU_PROMO_DISPATCH_URL", "").strip()
    token = os.environ.get("COMPUTEMESH_GPU_PROMO_DISPATCH_TOKEN", "").strip()
    if not base_url or not token:
        raise RuntimeError(
            "COMPUTEMESH_GPU_PROMO_DISPATCH_URL and COMPUTEMESH_GPU_PROMO_DISPATCH_TOKEN are required"
        )
    try:
        timeout = float(os.environ.get("COMPUTEMESH_GPU_PROMO_DISPATCH_TIMEOUT", "305"))
    except ValueError as exc:
        raise RuntimeError("COMPUTEMESH_GPU_PROMO_DISPATCH_TIMEOUT must be numeric") from exc
    return GpuPromoDispatchClient(
        base_url=base_url,
        bearer_token=token,
        timeout_seconds=timeout,
    )


__all__ = [
    "GpuPromoDispatchClient",
    "GpuPromoDispatchClientError",
    "build_gpu_promo_dispatch_client_from_env",
]
