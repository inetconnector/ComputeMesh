"""Active, bounded LAN discovery for provider dashboards.

UDP discovery is useful when a current node is listening, but older images or
firewalls can suppress broadcasts. This scanner complements it with a small
HTTP probe over the local private /24 networks and never treats a reachable
web server as a ComputeMesh node without the NodeOS marker.
"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, asdict
import ipaddress
import os
import re
import socket
import threading
import time
from typing import Any
import urllib.error
import urllib.request

DEFAULT_PORTS = (8080, 8081)
SCAN_TIMEOUT_SECONDS = 0.7
CACHE_TTL_SECONDS = 30.0
_CACHE_LOCK = threading.Lock()
_CACHE: tuple[float, list[dict[str, Any]]] | None = None


@dataclass(frozen=True)
class LanNode:
    ip: str
    port: int
    url: str
    product: str
    title: str
    current_version: str | None = None
    update_available: bool | None = None
    node_id: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _local_networks() -> list[ipaddress.IPv4Network]:
    candidates: set[str] = set()
    try:
        for info in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
            ip = str(info[4][0])
            if ipaddress.ip_address(ip).is_private and not ip.startswith("169.254."):
                candidates.add(ip)
    except OSError:
        pass
    # The dashboard runs on ordinary home LANs most often using /24. Operators
    # can add exact networks without widening the default probe.
    configured = [item.strip() for item in os.environ.get("COMPUTEMESH_LAN_CIDRS", "").split(",") if item.strip()]
    networks: set[ipaddress.IPv4Network] = set()
    for raw in configured:
        try:
            networks.add(ipaddress.ip_network(raw, strict=False))
        except ValueError:
            continue
    for ip in candidates:
        networks.add(ipaddress.ip_network(f"{ip}/24", strict=False))
    return sorted(networks, key=str)


def _probe(ip: str, port: int) -> LanNode | None:
    url = f"http://{ip}:{port}"
    try:
        with urllib.request.urlopen(f"{url}/", timeout=SCAN_TIMEOUT_SECONDS) as response:
            body = response.read(12000).decode("utf-8", errors="replace")
            title_match = re.search(r"<title[^>]*>(.*?)</title>", body, re.IGNORECASE | re.DOTALL)
            title = re.sub(r"\s+", " ", title_match.group(1)).strip() if title_match else ""
            marker = f"{title} {body[:4000]}".lower()
            if "computemesh" not in marker and "nodeos" not in marker:
                return None
    except (OSError, urllib.error.URLError, TimeoutError):
        return None

    current_version = None
    update_available = None
    try:
        with urllib.request.urlopen(f"{url}/api/action/check_update", timeout=SCAN_TIMEOUT_SECONDS) as response:
            payload = response.read(4096).decode("utf-8", errors="replace")
            import json
            data = json.loads(payload)
            current_version = str(data.get("current_version") or "") or None
            update_available = bool(data.get("update_available"))
    except Exception:
        pass
    return LanNode(
        ip=ip,
        port=port,
        url=f"{url}/",
        product="ComputeMesh NodeOS",
        title=title,
        current_version=current_version,
        update_available=update_available,
    )


def discover_lan_nodes(*, force: bool = False) -> list[dict[str, Any]]:
    """Return cached or freshly discovered ComputeMesh nodes on local LANs."""
    global _CACHE
    now = time.monotonic()
    with _CACHE_LOCK:
        if not force and _CACHE and now - _CACHE[0] < CACHE_TTL_SECONDS:
            return list(_CACHE[1])
    targets = [(str(ip), port) for network in _local_networks() for ip in network.hosts() for port in DEFAULT_PORTS]
    found: dict[tuple[str, int], dict[str, Any]] = {}
    with ThreadPoolExecutor(max_workers=64, thread_name_prefix="cm-lan-scan") as pool:
        futures = [pool.submit(_probe, ip, port) for ip, port in targets]
        for future in as_completed(futures):
            result = future.result()
            if result:
                found[(result.ip, result.port)] = result.to_dict()
    result = sorted(found.values(), key=lambda item: (item["ip"], item["port"]))
    with _CACHE_LOCK:
        _CACHE = (time.monotonic(), result)
    return list(result)
