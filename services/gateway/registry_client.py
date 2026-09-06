"""Read-only client for the private canonical model registry.

The gateway receives only the registry's public view.  The client validates the
response before it is used and keeps a short-lived last-known-good cache so a
transient control-plane failure does not turn an otherwise healthy gateway into
a model catalogue with fabricated metadata.
"""
from __future__ import annotations

from dataclasses import dataclass
import json
import os
import threading
import time
from urllib.error import URLError
from urllib.request import Request, urlopen
from typing import Any


class RegistryClientError(RuntimeError):
    """Raised when the configured registry cannot provide a valid catalogue."""


@dataclass(frozen=True)
class RegistryModel:
    id: str
    display_name: str
    context_length: int
    capabilities: tuple[str, ...]
    availability: str
    license: str
    artifact_digest: str = ""
    artifact_size_bytes: int = 0
    quantization: str = ""

    @property
    def available(self) -> bool:
        return self.availability in {"available_cold", "available_warm"}


def _parse_models(payload: Any) -> tuple[RegistryModel, ...]:
    if not isinstance(payload, dict) or payload.get("object") != "list":
        raise RegistryClientError("registry response is not a model list")
    raw_models = payload.get("data")
    if not isinstance(raw_models, list):
        raise RegistryClientError("registry response data is invalid")
    result: list[RegistryModel] = []
    for raw in raw_models:
        if not isinstance(raw, dict):
            raise RegistryClientError("registry model entry is invalid")
        model_id = str(raw.get("id", "")).strip()
        availability = str(raw.get("availability", "")).strip()
        if not model_id or availability not in {"available_cold", "available_warm", "warming", "unavailable", "draining"}:
            raise RegistryClientError("registry model entry has invalid identity or availability")
        capabilities = raw.get("capabilities", [])
        if not isinstance(capabilities, list) or not all(isinstance(item, str) for item in capabilities):
            raise RegistryClientError("registry model capabilities are invalid")
        try:
            context_length = int(raw.get("context_length", 0))
        except (TypeError, ValueError) as exc:
            raise RegistryClientError("registry context length is invalid") from exc
        if context_length < 1:
            raise RegistryClientError("registry context length must be positive")
        artifact = raw.get("artifact") or {}
        if not isinstance(artifact, dict):
            raise RegistryClientError("registry artifact is invalid")
        result.append(RegistryModel(
            id=model_id,
            display_name=str(raw.get("display_name", model_id)),
            context_length=context_length,
            capabilities=tuple(capabilities),
            availability=availability,
            license=str(raw.get("license", "unknown")),
            artifact_digest=str(artifact.get("digest", "")),
            artifact_size_bytes=int(artifact.get("size_bytes", 0) or 0),
            quantization=str(artifact.get("quantization", "")),
        ))
    return tuple(result)


class ModelRegistryClient:
    def __init__(self, url: str, *, bearer_token: str = "", timeout_seconds: float = 2.0, cache_ttl_seconds: float = 15.0) -> None:
        self.url = url.strip()
        self.bearer_token = bearer_token.strip()
        self.timeout_seconds = timeout_seconds
        self.cache_ttl_seconds = cache_ttl_seconds
        self._lock = threading.RLock()
        self._cached: tuple[RegistryModel, ...] | None = None
        self._cached_at = 0.0

    def models(self) -> tuple[RegistryModel, ...]:
        now = time.monotonic()
        with self._lock:
            if self._cached is not None and now - self._cached_at < self.cache_ttl_seconds:
                return self._cached
        headers = {"Accept": "application/json"}
        if self.bearer_token:
            headers["Authorization"] = f"Bearer {self.bearer_token}"
        try:
            with urlopen(Request(self.url, headers=headers), timeout=self.timeout_seconds) as response:
                payload = json.loads(response.read().decode("utf-8"))
            parsed = _parse_models(payload)
        except (OSError, URLError, TimeoutError, UnicodeError, json.JSONDecodeError, RegistryClientError) as exc:
            with self._lock:
                if self._cached is not None:
                    return self._cached
            raise RegistryClientError("configured model registry is unavailable") from exc
        with self._lock:
            self._cached = parsed
            self._cached_at = now
        return parsed


def build_registry_client_from_env() -> ModelRegistryClient | None:
    url = os.environ.get("COMPUTEMESH_MODEL_REGISTRY_URL", "").strip()
    if not url:
        return None
    try:
        timeout = float(os.environ.get("COMPUTEMESH_MODEL_REGISTRY_TIMEOUT_SECONDS", "2"))
        ttl = float(os.environ.get("COMPUTEMESH_MODEL_REGISTRY_CACHE_SECONDS", "15"))
    except ValueError as exc:
        raise RuntimeError("model registry timeout/cache settings must be numeric") from exc
    if timeout <= 0 or ttl < 0:
        raise RuntimeError("model registry timeout must be positive and cache must not be negative")
    return ModelRegistryClient(
        url,
        bearer_token=os.environ.get("COMPUTEMESH_MODEL_REGISTRY_TOKEN", ""),
        timeout_seconds=timeout,
        cache_ttl_seconds=ttl,
    )


__all__ = ["ModelRegistryClient", "RegistryClientError", "RegistryModel", "build_registry_client_from_env"]
