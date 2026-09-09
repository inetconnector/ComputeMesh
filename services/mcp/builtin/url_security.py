# SPDX-License-Identifier: Apache-2.0
"""Shared SSRF guard for MCP tools that contact user-selected public hosts.

The policy is deliberately conservative: only HTTP(S) targets whose complete
DNS result set consists of globally routable addresses are accepted. Redirects
are revalidated before urllib follows them.
"""

from __future__ import annotations

import ipaddress
import socket
import urllib.parse
import urllib.request
from dataclasses import dataclass
from typing import Iterable

BLOCKED_HOST_SUFFIXES = (
    ".localhost",
    ".local",
    ".internal",
    ".lan",
    ".home.arpa",
    ".corp",
    ".cluster.local",
)


class UnsafeTargetError(ValueError):
    """Raised when a URL/hostname violates the public-network policy."""


@dataclass(frozen=True)
class ResolvedPublicTarget:
    host: str
    port: int
    addresses: tuple[str, ...]


def is_ip_blocked(value: str) -> bool:
    """Return True unless ``value`` is a globally routable IP address."""
    try:
        ip = ipaddress.ip_address(value)
    except ValueError:
        return True
    return not ip.is_global


def _normalize_host(host: str) -> str:
    normalized = host.strip().lower().rstrip(".")
    if not normalized:
        raise UnsafeTargetError("Sicherheitsrichtlinie: Hostname fehlt.")
    if normalized == "localhost":
        raise UnsafeTargetError("Sicherheitsrichtlinie: localhost ist nicht erlaubt.")
    for suffix in BLOCKED_HOST_SUFFIXES:
        bare_suffix = suffix[1:]
        if normalized == bare_suffix or normalized.endswith(suffix):
            raise UnsafeTargetError(
                f"Sicherheitsrichtlinie: interne Domain-Endung '{suffix}' ist nicht erlaubt."
            )
    return normalized


def resolve_public_host(host: str, port: int) -> ResolvedPublicTarget:
    """Resolve a host and reject it if *any* returned address is non-public."""
    normalized = _normalize_host(host)
    try:
        literal = ipaddress.ip_address(normalized)
    except ValueError:
        literal = None

    if literal is not None:
        if is_ip_blocked(str(literal)):
            raise UnsafeTargetError(
                f"Sicherheitsrichtlinie: nicht-öffentliche IP '{literal}' ist nicht erlaubt."
            )
        return ResolvedPublicTarget(normalized, port, (str(literal),))

    try:
        addrinfo = socket.getaddrinfo(normalized, port, type=socket.SOCK_STREAM)
    except socket.gaierror as exc:
        raise UnsafeTargetError(f"DNS-Auflösung für '{normalized}' fehlgeschlagen: {exc}") from exc

    addresses: list[str] = []
    for _family, _socktype, _proto, _canonname, sockaddr in addrinfo:
        if not sockaddr:
            continue
        address = str(sockaddr[0])
        if is_ip_blocked(address):
            raise UnsafeTargetError(
                f"Sicherheitsrichtlinie: Host '{normalized}' löst auf nicht-öffentliche IP '{address}' auf."
            )
        if address not in addresses:
            addresses.append(address)

    if not addresses:
        raise UnsafeTargetError(f"Keine öffentliche IP für '{normalized}' gefunden.")
    return ResolvedPublicTarget(normalized, port, tuple(addresses))


def validate_public_url(url: str, *, allowed_schemes: Iterable[str] = ("http", "https")) -> ResolvedPublicTarget:
    """Validate an HTTP(S) URL and its current DNS resolution."""
    try:
        parsed = urllib.parse.urlsplit(url)
        port = parsed.port
    except ValueError as exc:
        raise UnsafeTargetError(f"Ungültige URL: {exc}") from exc

    schemes = {item.lower() for item in allowed_schemes}
    scheme = parsed.scheme.lower()
    if scheme not in schemes:
        raise UnsafeTargetError("Sicherheitsrichtlinie: nur HTTP/HTTPS-URLs sind erlaubt.")
    if parsed.username is not None or parsed.password is not None:
        raise UnsafeTargetError("Sicherheitsrichtlinie: Zugangsdaten in URLs sind nicht erlaubt.")
    if not parsed.hostname:
        raise UnsafeTargetError("Sicherheitsrichtlinie: URL enthält keinen Hostnamen.")

    effective_port = port or (443 if scheme == "https" else 80)
    if effective_port < 1 or effective_port > 65535:
        raise UnsafeTargetError("Sicherheitsrichtlinie: ungültiger Netzwerk-Port.")
    return resolve_public_host(parsed.hostname, effective_port)


class SafePublicRedirectHandler(urllib.request.HTTPRedirectHandler):
    """urllib redirect handler that re-runs SSRF validation for every hop."""

    max_repeats = 3
    max_redirections = 5

    def redirect_request(self, req, fp, code, msg, headers, newurl):  # noqa: ANN001
        absolute = urllib.parse.urljoin(req.full_url, newurl)
        validate_public_url(absolute)
        return super().redirect_request(req, fp, code, msg, headers, absolute)


def build_safe_public_opener() -> urllib.request.OpenerDirector:
    return urllib.request.build_opener(SafePublicRedirectHandler())
