from __future__ import annotations

import ipaddress
import socket
from urllib.parse import urljoin, urlsplit, urlunsplit, parse_qsl, urlencode

BLOCKED_HOSTNAMES = {"localhost", "localhost.localdomain", "metadata.google.internal"}
TRACKING_PREFIXES = ("utm_", "pk_", "mtm_")
TRACKING_KEYS = {"fbclid", "gclid", "msclkid", "mc_cid", "mc_eid", "ref", "source"}


def normalize_url(url: str, base: str | None = None) -> str:
    candidate = urljoin(base, url) if base else url
    parts = urlsplit(candidate)
    scheme = parts.scheme.lower()
    host = (parts.hostname or "").lower().rstrip(".")
    if scheme not in {"http", "https"} or not host:
        return ""
    port = parts.port
    netloc = host
    if port and not ((scheme == "http" and port == 80) or (scheme == "https" and port == 443)):
        netloc = f"{host}:{port}"
    path = parts.path or "/"
    while "//" in path:
        path = path.replace("//", "/")
    query = []
    for key, value in parse_qsl(parts.query, keep_blank_values=True):
        low = key.lower()
        if low.startswith(TRACKING_PREFIXES) or low in TRACKING_KEYS:
            continue
        query.append((key, value))
    return urlunsplit((scheme, netloc, path, urlencode(sorted(query)), ""))


def _public_ip(ip: str) -> bool:
    try:
        addr = ipaddress.ip_address(ip)
    except ValueError:
        return False
    return not (
        addr.is_private
        or addr.is_loopback
        or addr.is_link_local
        or addr.is_multicast
        or addr.is_reserved
        or addr.is_unspecified
    )


def validate_public_http_url(url: str, *, resolve_dns: bool = True) -> str:
    normalized = normalize_url(url)
    if not normalized:
        raise ValueError("Only absolute http/https URLs are allowed")
    parts = urlsplit(normalized)
    host = (parts.hostname or "").lower()
    if host in BLOCKED_HOSTNAMES:
        raise ValueError("Blocked hostname")
    try:
        literal = ipaddress.ip_address(host)
    except ValueError:
        literal = None
    if literal is not None and not _public_ip(host):
        raise ValueError("Blocked IP address")
    if resolve_dns:
        try:
            infos = socket.getaddrinfo(host, parts.port or (443 if parts.scheme == "https" else 80), type=socket.SOCK_STREAM)
        except socket.gaierror as exc:
            raise ValueError("DNS resolution failed") from exc
        addresses = {info[4][0] for info in infos}
        if not addresses or any(not _public_ip(ip) for ip in addresses):
            raise ValueError("DNS resolved to a non-public address")
    return normalized
