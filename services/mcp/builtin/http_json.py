# SPDX-License-Identifier: Apache-2.0
"""Small hardened HTTP/JSON helper for built-in MCP data providers.

This module is deliberately for provider URLs constructed by ComputeMesh itself.
User supplied URLs belong to the web-fetch/network-tool security path instead.
"""

from __future__ import annotations

import json
import socket
import urllib.error
import urllib.parse
import urllib.request
from typing import Any, Iterable

USER_AGENT = "ComputeMesh/1.2 (+https://mesh.inetconnector.com)"
DEFAULT_MAX_BYTES = 2 * 1024 * 1024


class ProviderError(RuntimeError):
    """Raised when a trusted upstream provider cannot return usable JSON."""


def _validated_provider_url(url: str, allowed_hosts: Iterable[str]) -> str:
    parsed = urllib.parse.urlsplit(url)
    host = (parsed.hostname or "").lower().rstrip(".")
    allowed = {item.lower().rstrip(".") for item in allowed_hosts}
    if parsed.scheme != "https" or not host or host not in allowed:
        raise ProviderError("Provider-URL wurde durch die Sicherheitsrichtlinie abgelehnt.")
    if parsed.username or parsed.password:
        raise ProviderError("Provider-URL darf keine Zugangsdaten enthalten.")
    return url


def fetch_json(
    url: str,
    *,
    allowed_hosts: Iterable[str],
    timeout: float = 8.0,
    max_bytes: int = DEFAULT_MAX_BYTES,
    headers: dict[str, str] | None = None,
) -> Any:
    """Fetch JSON from one explicitly allow-listed HTTPS provider.

    The response body is bounded before decoding so a broken/malicious provider
    cannot cause unbounded memory use. Network and JSON failures are normalized
    into ``ProviderError`` for stable MCP error handling and deterministic tests.
    """
    if timeout <= 0:
        raise ProviderError("Provider-Timeout muss größer als 0 sein.")
    if max_bytes < 1:
        raise ProviderError("Provider-Antwortlimit muss größer als 0 sein.")

    _validated_provider_url(url, allowed_hosts)
    request_headers = {
        "User-Agent": USER_AGENT,
        "Accept": "application/json, application/vnd.api+json",
    }
    if headers:
        request_headers.update(headers)
    req = urllib.request.Request(url, headers=request_headers)

    try:
        with urllib.request.urlopen(req, timeout=timeout) as response:
            status = getattr(response, "status", 200)
            if status is not None and not 200 <= int(status) < 300:
                raise ProviderError(f"Provider antwortete mit HTTP {status}.")
            raw = response.read(max_bytes + 1)
    except urllib.error.HTTPError as exc:
        raise ProviderError(f"Provider antwortete mit HTTP {exc.code}.") from exc
    except (urllib.error.URLError, TimeoutError, socket.timeout, OSError) as exc:
        reason = getattr(exc, "reason", exc)
        raise ProviderError(f"Provider nicht erreichbar: {reason}") from exc

    if len(raw) > max_bytes:
        raise ProviderError("Provider-Antwort überschreitet das Größenlimit.")
    if not raw:
        raise ProviderError("Provider lieferte eine leere Antwort.")

    try:
        return json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ProviderError("Provider lieferte kein gültiges UTF-8-JSON.") from exc
