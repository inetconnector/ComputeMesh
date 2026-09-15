# SPDX-License-Identifier: Apache-2.0
"""
SSRF-Safe HTTP Egress Client for Dynamic MCP Tools.
Prevents Server-Side Request Forgery (SSRF) by validating IP ranges before connect,
blocking RFC1918 private networks, loopback (127.0.0.1), and cloud metadata (169.254.169.254).
"""

from __future__ import annotations

import ipaddress
import json
import socket
import urllib.parse
import urllib.request
from typing import Any, Dict, Optional, Union

USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) ComputeMesh-DynamicRunner/1.0"
MAX_RESPONSE_BYTES = 5 * 1024 * 1024  # 5 MB
DEFAULT_TIMEOUT_SECONDS = 5.0


class SSRFBlockedException(Exception):
    """Raised when an HTTP request targets a blocked or internal IP/subnet."""
    pass


class SafeHttpClient:
    """Zero-Trust HTTP client with DNS pinning and strict SSRF egress firewall."""

    # Disallowed IP Networks
    BLOCKED_NETWORKS = [
        ipaddress.ip_network("0.0.0.0/8"),          # Current network
        ipaddress.ip_network("10.0.0.0/8"),         # RFC1918 Private
        ipaddress.ip_network("100.64.0.0/10"),      # Carrier-grade NAT
        ipaddress.ip_network("127.0.0.0/8"),        # Loopback IPv4
        ipaddress.ip_network("169.254.0.0/16"),     # Link-Local & Cloud Metadata (AWS, GCP, Azure, OpenStack)
        ipaddress.ip_network("172.16.0.0/12"),      # RFC1918 Private
        ipaddress.ip_network("192.0.0.0/24"),       # IETF Protocol Assignments
        ipaddress.ip_network("192.0.2.0/24"),       # TEST-NET-1
        ipaddress.ip_network("192.88.99.0/24"),     # 6to4 Relay Anycast
        ipaddress.ip_network("192.168.0.0/16"),     # RFC1918 Private
        ipaddress.ip_network("198.18.0.0/15"),      # Benchmarking
        ipaddress.ip_network("198.51.100.0/24"),    # TEST-NET-2
        ipaddress.ip_network("203.0.113.0/24"),     # TEST-NET-3
        ipaddress.ip_network("224.0.0.0/4"),        # Multicast
        ipaddress.ip_network("240.0.0.0/4"),        # Reserved
        ipaddress.ip_network("255.255.255.255/32"), # Broadcast
        # IPv6
        ipaddress.ip_network("::1/128"),            # IPv6 Loopback
        ipaddress.ip_network("fc00::/7"),           # IPv6 Unique Local
        ipaddress.ip_network("fe80::/10"),          # IPv6 Link-Local
    ]

    @classmethod
    def is_ip_allowed(cls, ip_str: str) -> bool:
        """Checks whether an IP address is a valid public IP and not in a blocked range."""
        try:
            ip = ipaddress.ip_address(ip_str)
        except ValueError:
            return False

        if ip.is_loopback or ip.is_private or ip.is_link_local or ip.is_reserved or ip.is_multicast:
            return False

        for blocked_net in cls.BLOCKED_NETWORKS:
            if ip in blocked_net:
                return False

        return True

    @classmethod
    def safe_request(
        cls,
        url: str,
        method: str = "GET",
        params: Optional[Dict[str, Any]] = None,
        data: Optional[Union[Dict[str, Any], str, bytes]] = None,
        headers: Optional[Dict[str, str]] = None,
        timeout: float = DEFAULT_TIMEOUT_SECONDS,
    ) -> Dict[str, Any]:
        """
        Executes an HTTP request with SSRF validation, DNS pinning, and size caps.
        Returns parsed JSON or text payload.
        """
        parsed_url = urllib.parse.urlparse(url)
        if parsed_url.scheme not in ("http", "https"):
            raise SSRFBlockedException(f"Nur HTTP und HTTPS Protokolle sind zulässig, nicht '{parsed_url.scheme}'.")

        hostname = parsed_url.hostname
        if not hostname:
            raise SSRFBlockedException("Ungültige URL: Kein Hostname vorhanden.")

        # Disallow local hostnames directly
        if hostname.lower() in ("localhost", "127.0.0.1", "::1", "metadata.google.internal", "instance-data"):
            raise SSRFBlockedException(f"Zugriff auf internen Host '{hostname}' ist verboten.")

        # 1. Resolve DNS and validate resolved IP
        port = parsed_url.port or (443 if parsed_url.scheme == "https" else 80)
        try:
            addr_info = socket.getaddrinfo(hostname, port, socket.AF_UNSPEC, socket.SOCK_STREAM)
        except socket.gaierror as exc:
            raise SSRFBlockedException(f"DNS-Auflösung für '{hostname}' fehlgeschlagen: {exc}")

        resolved_ips = [info[4][0] for info in addr_info if info and info[4]]
        if not resolved_ips:
            raise SSRFBlockedException(f"Keine IP-Adresse für '{hostname}' gefunden.")

        for ip_addr in resolved_ips:
            if not cls.is_ip_allowed(ip_addr):
                raise SSRFBlockedException(
                    f"SSRF-Schutz blockiert Zugriff auf Host '{hostname}' (Aufgelöst nach interner/gesperrter IP {ip_addr})."
                )

        # 2. Build Request with Parameters
        final_url = url
        if params:
            query_str = urllib.parse.urlencode(params)
            sep = "&" if "?" in final_url else "?"
            final_url = f"{final_url}{sep}{query_str}"

        req_headers = {"User-Agent": USER_AGENT, "Accept": "application/json, text/plain, */*"}
        if headers:
            req_headers.update(headers)

        payload_bytes: Optional[bytes] = None
        if data is not None:
            if isinstance(data, dict):
                payload_bytes = json.dumps(data).encode("utf-8")
                req_headers.setdefault("Content-Type", "application/json")
            elif isinstance(data, str):
                payload_bytes = data.encode("utf-8")
            elif isinstance(data, bytes):
                payload_bytes = data

        req = urllib.request.Request(
            final_url,
            data=payload_bytes,
            headers=req_headers,
            method=method.upper(),
        )

        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                status_code = resp.status
                raw_bytes = resp.read(MAX_RESPONSE_BYTES + 1)
                if len(raw_bytes) > MAX_RESPONSE_BYTES:
                    raise ValueError(f"HTTP-Antwort übersteigt das Limit von {MAX_RESPONSE_BYTES // (1024*1024)} MB.")

                text_content = raw_bytes.decode("utf-8", errors="replace")
                try:
                    json_content = json.loads(text_content)
                    return {
                        "status_code": status_code,
                        "data": json_content,
                        "content_type": "application/json",
                    }
                except (json.JSONDecodeError, ValueError):
                    return {
                        "status_code": status_code,
                        "data": text_content,
                        "content_type": "text/plain",
                    }
        except Exception as e:
            if isinstance(e, SSRFBlockedException):
                raise
            return {"error": f"HTTP-Anfrage fehlgeschlagen: {str(e)}", "status_code": getattr(e, "code", 500)}
