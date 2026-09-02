"""Fail-closed client for the private hardware-promo control-plane boundary."""
from __future__ import annotations

import json
import os
import ssl
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

_MAX_RESPONSE_BYTES = 512 * 1024


class PromoControlPlaneError(RuntimeError):
    """Private promo service is unavailable or rejected a request."""

    def __init__(self, message: str, *, status_code: int | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code


@dataclass(frozen=True)
class PromoControlPlaneClient:
    base_url: str
    bearer_token: str
    timeout_seconds: float = 5.0
    ca_file: str = ""

    def __post_init__(self) -> None:
        parsed = urlparse(self.base_url)
        if parsed.scheme not in {"https", "http"} or not parsed.hostname:
            raise ValueError("promo control-plane URL must be absolute http(s)")
        if parsed.scheme == "http" and parsed.hostname not in {
            "127.0.0.1",
            "localhost",
            "::1",
        }:
            raise ValueError("plaintext promo control-plane transport is loopback-only")
        if len(self.bearer_token.strip()) < 24:
            raise ValueError("promo control-plane token must be at least 24 characters")
        if self.timeout_seconds <= 0 or self.timeout_seconds > 30:
            raise ValueError("promo control-plane timeout must be in (0, 30] seconds")

    def _context(self) -> ssl.SSLContext | None:
        if urlparse(self.base_url).scheme != "https":
            return None
        return ssl.create_default_context(cafile=self.ca_file or None)

    def _post(self, path: str, body: dict[str, Any]) -> dict[str, Any]:
        raw = json.dumps(body, sort_keys=True, separators=(",", ":")).encode("utf-8")
        request = urllib.request.Request(
            self.base_url.rstrip("/") + path,
            data=raw,
            headers={
                "Authorization": f"Bearer {self.bearer_token}",
                "Content-Type": "application/json",
                "Accept": "application/json",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(
                request,
                timeout=self.timeout_seconds,
                context=self._context(),
            ) as response:
                payload = response.read(_MAX_RESPONSE_BYTES + 1)
                if len(payload) > _MAX_RESPONSE_BYTES:
                    raise PromoControlPlaneError("promo control-plane response is too large")
                if int(response.status) != 200:
                    raise PromoControlPlaneError(
                        "promo control-plane returned an unexpected status",
                        status_code=int(response.status),
                    )
        except urllib.error.HTTPError as exc:
            try:
                exc.read(_MAX_RESPONSE_BYTES + 1)
            except Exception:
                pass
            raise PromoControlPlaneError(
                "promo control-plane rejected the request",
                status_code=int(exc.code),
            ) from exc
        except (urllib.error.URLError, TimeoutError, OSError, ssl.SSLError) as exc:
            raise PromoControlPlaneError("promo control-plane is unavailable") from exc

        try:
            value = json.loads(payload.decode("utf-8"))
        except (UnicodeError, json.JSONDecodeError) as exc:
            raise PromoControlPlaneError("promo control-plane returned invalid JSON") from exc
        if not isinstance(value, dict):
            raise PromoControlPlaneError("promo control-plane response must be an object")
        return value

    def issue_challenge(self, body: dict[str, Any]) -> dict[str, Any]:
        return self._post("/internal/v1/promo/challenge", body)

    def verify_and_issue(self, body: dict[str, Any]) -> dict[str, Any]:
        return self._post("/internal/v1/promo/verify", body)


def build_promo_control_plane_client_from_env() -> PromoControlPlaneClient:
    base_url = os.environ.get("COMPUTEMESH_PROMO_CONTROL_PLANE_URL", "").strip()
    token = os.environ.get("COMPUTEMESH_PROMO_CONTROL_PLANE_TOKEN", "").strip()
    if not base_url or not token:
        raise RuntimeError(
            "COMPUTEMESH_PROMO_CONTROL_PLANE_URL and COMPUTEMESH_PROMO_CONTROL_PLANE_TOKEN are required"
        )
    try:
        timeout = float(os.environ.get("COMPUTEMESH_PROMO_CONTROL_PLANE_TIMEOUT", "5"))
    except ValueError as exc:
        raise RuntimeError("COMPUTEMESH_PROMO_CONTROL_PLANE_TIMEOUT must be numeric") from exc
    ca_file = os.environ.get("COMPUTEMESH_PROMO_CONTROL_PLANE_CA_FILE", "").strip()
    if ca_file and not Path(ca_file).is_file():
        raise RuntimeError("COMPUTEMESH_PROMO_CONTROL_PLANE_CA_FILE does not exist")
    return PromoControlPlaneClient(
        base_url=base_url,
        bearer_token=token,
        timeout_seconds=timeout,
        ca_file=ca_file,
    )
