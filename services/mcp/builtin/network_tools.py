# SPDX-License-Identifier: Apache-2.0
"""Safe owner-only network diagnostics for public Internet hosts."""

from __future__ import annotations

import ipaddress
import re
import socket
import ssl
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from typing import Any, Dict, Optional, Tuple

from .url_security import (
    BLOCKED_HOST_SUFFIXES,
    UnsafeTargetError,
    build_safe_public_opener,
    is_ip_blocked,
    resolve_public_host,
    validate_public_url,
)

USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) ComputeMesh/1.2 NetworkAudit"


def _is_ip_blocked(ip_str: str) -> bool:
    """Backwards-compatible wrapper around the shared public-IP policy."""
    return is_ip_blocked(ip_str)


def _sanitize_and_validate_host(target: str) -> Tuple[Optional[str], Optional[str]]:
    """Normalize a hostname/IP and reject obvious internal hostnames."""
    raw = str(target or "").strip()
    if not raw:
        return None, "Hostname darf nicht leer sein."

    try:
        if "://" in raw:
            parsed = urllib.parse.urlsplit(raw)
            host = parsed.hostname or ""
        else:
            # Preserve bare IPv6 literals; for normal names remove path/port.
            try:
                ipaddress.ip_address(raw.strip("[]"))
                host = raw.strip("[]")
            except ValueError:
                parsed = urllib.parse.urlsplit("//" + raw)
                host = parsed.hostname or raw.split("/", 1)[0]
    except ValueError:
        return None, "Ungültiges Format für Hostname."

    host = host.lower().rstrip(".")
    if not host or host == "localhost":
        return None, "Sicherheitsrichtlinie: Zugriff auf localhost/interne Adressen verweigert."
    for suffix in BLOCKED_HOST_SUFFIXES:
        if host == suffix[1:] or host.endswith(suffix):
            return None, f"Sicherheitsrichtlinie: Zugriff auf interne Domain-Endung '{suffix}' verweigert."

    try:
        ipaddress.ip_address(host)
        return host, None
    except ValueError:
        pass
    if not re.match(r"^[a-z0-9.-]+$", host):
        return None, "Ungültiges Format für Hostname (nur DNS-Hostname oder IP-Adresse erlaubt)."
    return host, None


def _check_dns(host: str) -> Dict[str, Any]:
    """Resolve all addresses and fail if any address is not globally routable."""
    try:
        resolved = resolve_public_host(host, 443)
    except UnsafeTargetError as exc:
        return {"error": str(exc)}

    result: Dict[str, Any] = {"host": host, "ipv4": [], "ipv6": [], "status": "ok"}
    for value in resolved.addresses:
        try:
            ip = ipaddress.ip_address(value)
        except ValueError:
            continue
        key = "ipv4" if ip.version == 4 else "ipv6"
        result[key].append(value)
    return result


def _check_ssl(host: str, port: int = 443, timeout: float = 3.5) -> Dict[str, Any]:
    """Validate the TLS certificate while connecting to a prevalidated public IP."""
    context = ssl.create_default_context()
    context.check_hostname = True
    context.verify_mode = ssl.CERT_REQUIRED

    try:
        resolved = resolve_public_host(host, port)
        # Connecting to the already resolved public address reduces DNS-rebinding
        # exposure; TLS still verifies the original hostname via SNI.
        address = resolved.addresses[0]
        with socket.create_connection((address, port), timeout=timeout) as sock:
            with context.wrap_socket(sock, server_hostname=host) as ssock:
                cert = ssock.getpeercert()
                if not cert:
                    return {"status": "no_cert", "error": "Kein SSL-Zertifikat empfangen"}

                not_after_str = cert.get("notAfter", "")
                not_before_str = cert.get("notBefore", "")
                expire_dt = datetime.strptime(not_after_str, "%b %d %H:%M:%S %Y %Z").replace(tzinfo=timezone.utc)
                days_left = (expire_dt - datetime.now(timezone.utc)).days
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
    except UnsafeTargetError as exc:
        return {"valid": False, "error": str(exc)}
    except ssl.SSLCertVerificationError as exc:
        return {"valid": False, "error": f"Zertifikatsvalidierung fehlgeschlagen: {exc.verify_message}"}
    except Exception as exc:
        return {"valid": False, "error": f"SSL-Verbindung fehlgeschlagen: {exc}"}


def _check_http(host: str, timeout: float = 3.5) -> Dict[str, Any]:
    """Probe HTTP(S), validating initial targets and every redirect hop."""
    results: Dict[str, Any] = {}
    opener = build_safe_public_opener()
    for proto in ("https", "http"):
        url = f"{proto}://{host}/"
        start_t = time.perf_counter()
        try:
            validate_public_url(url)
            req = urllib.request.Request(
                url,
                headers={"User-Agent": USER_AGENT, "Accept": "*/*"},
                method="HEAD",
            )
            with opener.open(req, timeout=timeout) as resp:
                final_url = resp.geturl() if hasattr(resp, "geturl") else url
                validate_public_url(final_url)
                elapsed_ms = round((time.perf_counter() - start_t) * 1000, 1)
                results[proto] = {
                    "status_code": resp.status,
                    "reason": resp.reason,
                    "latency_ms": elapsed_ms,
                    "server": resp.headers.get("Server", "Unbekannt"),
                    "content_type": resp.headers.get("Content-Type", ""),
                    "redirect_url": final_url if final_url != url else None,
                }
        except UnsafeTargetError as exc:
            results[proto] = {"error": str(exc)}
        except urllib.error.HTTPError as exc:
            elapsed_ms = round((time.perf_counter() - start_t) * 1000, 1)
            results[proto] = {
                "status_code": exc.code,
                "reason": exc.reason,
                "latency_ms": elapsed_ms,
                "server": exc.headers.get("Server", "Unbekannt") if exc.headers else "Unbekannt",
            }
        except Exception as exc:
            results[proto] = {"error": str(exc)}
    return results


def lookup_network_host(
    host: str = "",
    target: str = "",
    domain: str = "",
    check_type: str = "all",
    timeout: float = 5.0,
) -> Dict[str, Any]:
    """Inspect DNS, HTTP(S), and TLS for an explicitly public host."""
    raw_host = host or target or domain or ""
    clean_host, err = _sanitize_and_validate_host(raw_host)
    if err or not clean_host:
        return {"error": err or "Ungültiger Hostname."}

    try:
        timeout_value = float(timeout)
    except (TypeError, ValueError):
        return {"error": "timeout muss numerisch sein."}
    if timeout_value <= 0 or timeout_value > 30:
        return {"error": "timeout muss zwischen 0 und 30 Sekunden liegen."}

    dns_info = _check_dns(clean_host)
    if "error" in dns_info:
        return dns_info

    check_mode = (check_type or "all").lower().strip()
    if check_mode not in {"all", "dns_only", "http", "ssl"}:
        return {"error": "check_type muss all, dns_only, http oder ssl sein."}

    result: Dict[str, Any] = {
        "host": clean_host,
        "dns": dns_info,
        "checked_at": datetime.now(timezone.utc).isoformat(),
    }
    if check_mode == "dns_only":
        return result
    if check_mode in ("all", "http"):
        result["http"] = _check_http(clean_host, timeout=min(timeout_value / 2, 3.5))
    if check_mode in ("all", "ssl"):
        result["ssl_certificate"] = _check_ssl(clean_host, timeout=min(timeout_value / 2, 3.5))
    return result


inspect_host = lookup_network_host
