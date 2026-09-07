# SPDX-License-Identifier: Apache-2.0
"""
Safe Network Diagnostics & Host Inspection Tool (Owner Key Restricted).
Performs public DNS queries, HTTP/HTTPS status checks, and SSL certificate validation.
Includes rigorous SSRF protections blocking private networks, loopbacks, and internal IPs.
"""

from __future__ import annotations

import ipaddress
import re
import socket
import ssl
import time
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) ComputeMesh/1.2 NetworkAudit"

# Forbidden IP ranges for strict SSRF protection
BLOCKED_IP_NETWORKS = [
    ipaddress.ip_network("0.0.0.0/8"),
    ipaddress.ip_network("10.0.0.0/8"),
    ipaddress.ip_network("100.64.0.0/10"),
    ipaddress.ip_network("127.0.0.0/8"),
    ipaddress.ip_network("169.254.0.0/16"),
    ipaddress.ip_network("172.16.0.0/12"),
    ipaddress.ip_network("192.168.0.0/16"),
    ipaddress.ip_network("198.18.0.0/15"),
    ipaddress.ip_network("224.0.0.0/4"),
    ipaddress.ip_network("240.0.0.0/4"),
    ipaddress.ip_network("::1/128"),
    ipaddress.ip_network("fc00::/7"),
    ipaddress.ip_network("fe80::/10"),
]

BLOCKED_HOST_SUFFIXES = (
    ".localhost",
    ".local",
    ".internal",
    ".lan",
    ".home.arpa",
    ".corp",
    ".cluster.local",
)


def _is_ip_blocked(ip_str: str) -> bool:
    """Checks whether an IP address belongs to private, loopback, or reserved networks."""
    try:
        ip = ipaddress.ip_address(ip_str)
        if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_multicast or ip.is_reserved or ip.is_unspecified:
            return True
        for net in BLOCKED_IP_NETWORKS:
            if ip in net:
                return True
        return False
    except ValueError:
        return True


def _sanitize_and_validate_host(target: str) -> Tuple[Optional[str], Optional[str]]:
    """
    Validates host string and strips protocol schemes.
    Returns (cleaned_host, error_message).
    """
    raw = target.strip().lower()
    if not raw:
        return None, "Hostname darf nicht leer sein."

    # Strip scheme if user passed http:// or https://
    if "://" in raw:
        parsed = urllib.parse.urlparse(raw)
        raw = parsed.netloc or parsed.path

    # Strip port if present
    if ":" in raw:
        raw = raw.split(":")[0]

    # Strip trailing slashes or paths
    raw = raw.split("/")[0].strip()

    if not raw or raw == "localhost" or raw.startswith("127.") or raw.startswith("0."):
        return None, "Sicherheitsrichtlinie: Zugriff auf 'localhost' oder interne Adressen verweigert."

    for suffix in BLOCKED_HOST_SUFFIXES:
        if raw.endswith(suffix):
            return None, f"Sicherheitsrichtlinie: Zugriff auf interne Domain-Endung '{suffix}' verweigert."

    # Validate characters (domain name or IP)
    if not re.match(r"^[a-z0-9.-]+$", raw):
        return None, "Ungültiges Format für Hostname (nur Kleinbuchstaben, Ziffern, '.' und '-' erlaubt)."

    return raw, None


def _check_dns(host: str) -> Dict[str, Any]:
    """Resolves IPv4 and IPv6 addresses and checks for SSRF targets."""
    dns_res: Dict[str, Any] = {"host": host, "ipv4": [], "ipv6": [], "status": "ok"}
    try:
        addrinfo = socket.getaddrinfo(host, None)
        for family, _, _, _, sockaddr in addrinfo:
            ip = sockaddr[0]
            if family == socket.AF_INET and ip not in dns_res["ipv4"]:
                if _is_ip_blocked(ip):
                    return {"error": f"Sicherheitsverstoß: Host '{host}' löst auf private/lokale IP '{ip}' auf. Anfrage blockiert."}
                dns_res["ipv4"].append(ip)
            elif family == socket.AF_INET6 and ip not in dns_res["ipv6"]:
                if _is_ip_blocked(ip):
                    return {"error": f"Sicherheitsverstoß: Host '{host}' löst auf private/lokale IPv6 '{ip}' auf. Anfrage blockiert."}
                dns_res["ipv6"].append(ip)
    except Exception as e:
        return {"error": f"DNS-Auflösung für '{host}' fehlgeschlagen: {str(e)}"}

    if not dns_res["ipv4"] and not dns_res["ipv6"]:
        return {"error": f"Keine DNS-Einträge für Host '{host}' gefunden."}

    return dns_res


def _check_ssl(host: str, port: int = 443, timeout: float = 3.5) -> Dict[str, Any]:
    """Validates TLS/SSL certificate and calculates expiration date."""
    context = ssl.create_default_context()
    context.check_hostname = True
    context.verify_mode = ssl.CERT_REQUIRED

    try:
        with socket.create_connection((host, port), timeout=timeout) as sock:
            with context.wrap_socket(sock, server_hostname=host) as ssock:
                cert = ssock.getpeercert()
                if not cert:
                    return {"status": "no_cert", "error": "Kein SSL-Zertifikat empfangen"}

                not_after_str = cert.get("notAfter", "")
                not_before_str = cert.get("notBefore", "")

                # Parse date format: 'May 24 12:00:00 2025 GMT'
                expire_dt = datetime.strptime(not_after_str, "%b %d %H:%M:%S %Y %Z").replace(tzinfo=timezone.utc)
                now_dt = datetime.now(timezone.utc)
                days_left = (expire_dt - now_dt).days

                subject_dict = dict(x[0] for x in cert.get("subject", ()))
                issuer_dict = dict(x[0] for x in cert.get("issuer", ()))

                return {
                    "valid": days_left > 0,
                    "days_until_expiry": days_left,
                    "valid_until": expire_dt.strftime("%Y-%m-%d %H:%M:%S UTC"),
                    "valid_from": not_before_str,
                    "subject_cn": subject_dict.get("commonName", ""),
                    "issuer_org": issuer_dict.get("organizationName", issuer_dict.get("commonName", "")),
                    "tls_version": ssock.version(),
                }
    except ssl.SSLCertVerificationError as se:
        return {"valid": False, "error": f"Zertifikatsvalidierung fehlgeschlagen: {se.verify_message}"}
    except Exception as e:
        return {"valid": False, "error": f"SSL-Verbindung fehlgeschlagen: {str(e)}"}


def _check_http(host: str, timeout: float = 3.5) -> Dict[str, Any]:
    """Probes HTTP and HTTPS endpoints for status code, latency, and server header."""
    results: Dict[str, Any] = {}
    for proto in ("https", "http"):
        url = f"{proto}://{host}/"
        start_t = time.perf_counter()
        req = urllib.request.Request(
            url,
            headers={"User-Agent": USER_AGENT, "Accept": "*/*"},
            method="HEAD",
        )
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                elapsed_ms = round((time.perf_counter() - start_t) * 1000, 1)
                results[proto] = {
                    "status_code": resp.status,
                    "reason": resp.reason,
                    "latency_ms": elapsed_ms,
                    "server": resp.headers.get("Server", "Unbekannt"),
                    "content_type": resp.headers.get("Content-Type", ""),
                    "redirect_url": resp.geturl() if resp.geturl() != url else None,
                }
        except urllib.error.HTTPError as he:
            elapsed_ms = round((time.perf_counter() - start_t) * 1000, 1)
            results[proto] = {
                "status_code": he.code,
                "reason": he.reason,
                "latency_ms": elapsed_ms,
                "server": he.headers.get("Server", "Unbekannt"),
            }
        except Exception as e:
            results[proto] = {"error": str(e)}

    return results


def lookup_network_host(
    host: str = "",
    target: str = "",
    domain: str = "",
    check_type: str = "all",
    timeout: float = 5.0,
) -> Dict[str, Any]:
    """
    Safely inspects a public domain or host (DNS records, HTTP/HTTPS availability, SSL certificate).
    Restricted to authorized fleet owners with SSRF prevention.
    """
    raw_host = host or target or domain or ""
    clean_host, err = _sanitize_and_validate_host(raw_host)
    if err or not clean_host:
        return {"error": err or "Ungültiger Hostname."}

    # 1. First resolve DNS and check for forbidden SSRF IP ranges
    dns_info = _check_dns(clean_host)
    if "error" in dns_info:
        return dns_info

    check_mode = (check_type or "all").lower().strip()
    result: Dict[str, Any] = {
        "host": clean_host,
        "dns": dns_info,
        "checked_at": datetime.now(timezone.utc).isoformat(),
    }

    if check_mode in ("all", "dns_only"):
        if check_mode == "dns_only":
            return result

    # 2. HTTP/HTTPS probe
    if check_mode in ("all", "http"):
        http_info = _check_http(clean_host, timeout=min(timeout / 2, 3.5))
        result["http"] = http_info

    # 3. SSL certificate check
    if check_mode in ("all", "ssl"):
        ssl_info = _check_ssl(clean_host, timeout=min(timeout / 2, 3.5))
        result["ssl_certificate"] = ssl_info

    return result


# Backwards-compatible alias
inspect_host = lookup_network_host
