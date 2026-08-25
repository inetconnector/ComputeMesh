"""ComputeMesh Network Interface & Routing Detector."""
from __future__ import annotations

import platform
import socket
import subprocess
from typing import Any

from config import CONFIG
from services.appliance_dashboard.tunnel_relay import NODE_AUTH_TOKEN


def get_network_interfaces(node_id: str = "cm-laptop-node", auth_token: str = "") -> list[dict[str, str]]:
    interfaces: list[dict[str, str]] = []
    seen_ips = set()

    token = auth_token or NODE_AUTH_TOKEN
    tunnel_url = CONFIG.endpoints.get_node_tunnel_url(node_id=node_id, auth_token=token)

    # 0. Official Web Portal Encrypted Cloud Tunnel (Reachable on every phone / browser worldwide)
    interfaces.append({
        "interface": "tunnel",
        "ip": CONFIG.endpoints.host,
        "url": tunnel_url,
        "config_url": f"{tunnel_url}#config",
    })

    # 1. Primary physical LAN socket IP (e.g. 192.168.1.94)
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        primary_ip = s.getsockname()[0]
        s.close()
        if primary_ip and not primary_ip.startswith("127."):
            seen_ips.add(primary_ip)
            interfaces.append({
                "interface": "lan",
                "ip": primary_ip,
                "url": f"http://{primary_ip}:8080/",
                "config_url": f"http://{primary_ip}:8080/#config",
            })
    except Exception:
        pass

    # 2. Hostname resolution (sort home LAN 192.168.* / 10.* before virtual 172.*)
    try:
        host_name = socket.gethostname()
        for ip in socket.gethostbyname_ex(host_name)[2]:
            if not ip.startswith("127.") and ip not in seen_ips:
                seen_ips.add(ip)
                interfaces.append({
                    "interface": "lan",
                    "ip": ip,
                    "url": f"http://{ip}:8080/",
                    "config_url": f"http://{ip}:8080/#config",
                })
    except Exception:
        pass

    # 3. Linux ip addr command
    if platform.system().lower() == "linux":
        try:
            out = subprocess.check_output(["ip", "-o", "-4", "addr", "show"], text=True, timeout=2)
            for line in out.splitlines():
                parts = line.split()
                if len(parts) >= 4:
                    iface = parts[1]
                    ip = parts[3].split("/")[0]
                    if not ip.startswith("127.") and ip not in seen_ips:
                        seen_ips.add(ip)
                        interfaces.append({
                            "interface": iface,
                            "ip": ip,
                            "url": f"http://{ip}:8080/",
                            "config_url": f"http://{ip}:8080/#config",
                        })
        except Exception:
            pass

    return interfaces
