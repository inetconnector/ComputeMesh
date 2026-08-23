#!/usr/bin/env python3
"""ComputeMesh Console & Monitor IP Display Banner Generator.

Runs at system startup on NodeOS / Linux to detect all assigned network IP addresses
and print a prominent, high-visibility banner to the physical monitor (tty1, /etc/issue,
/etc/motd) so miners can see the exact browser URLs without attaching a keyboard/mouse.
"""
from __future__ import annotations

import os
from pathlib import Path
import platform
import socket
import subprocess
import sys


def get_all_ips() -> list[tuple[str, str]]:
    """Return list of (interface_name, ip_address) tuples."""
    results = []
    seen = set()

    if platform.system().lower() == "linux":
        try:
            out = subprocess.check_output(["ip", "-o", "-4", "addr", "show"], text=True, timeout=3)
            for line in out.splitlines():
                parts = line.split()
                if len(parts) >= 4:
                    iface = parts[1]
                    ip = parts[3].split("/")[0]
                    if not ip.startswith("127.") and ip not in seen:
                        seen.add(ip)
                        results.append((iface, ip))
        except Exception:
            pass

    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        primary = s.getsockname()[0]
        s.close()
        if primary and not primary.startswith("127.") and primary not in seen:
            seen.add(primary)
            results.insert(0, ("primary", primary))
    except Exception:
        pass

    return results


def format_banner() -> str:
    ips = get_all_ips()
    lines = [
        "\033[1;36m",
        "================================================================================",
        "   ____                            _         __  __           _     ",
        "  / ___|___  _ __ ___  _ __  _   _| |_ ___  |  \/  | ___  ___| |__  ",
        " | |   / _ \\| '_ ` _ \\| '_ \\| | | | __/ _ \\ | |\\/| |/ _ \\/ __| '_ \\ ",
        " | |__| (_) | | | | | | |_) | |_| | ||  __/ | |  | |  __/\\__ \\ | | |",
        "  \\____\\___/|_| |_| |_| .__/ \\__,_|\\__\\___| |_|  |_|\\___||___/_| |_|",
        "                      |_|  NodeOS Provider Appliance (AMD + NVIDIA Native)",
        "================================================================================",
        "\033[0m",
        "\033[1;32m  [STATUS] Node is ONLINE and Serving Decentralized AI Compute\033[0m",
        "",
        "\033[1;33m  >>> REMOTE DASHBOARD & WALLET CONFIGURATION (NO KEYBOARD NEEDED) <<<\033[0m",
        "  Öffne diese Adresse in einem beliebigen Browser auf deinem PC, Mac oder Smartphone:",
        "",
    ]

    if ips:
        for iface, ip in ips:
            lines.append(f"  \033[1;36m• {iface.upper()}:\033[0m  \033[1;37mhttp://{ip}:8080/\033[0m  (Einstellungen: \033[1;32mhttp://{ip}:8080/#config\033[0m)")
    else:
        lines.append("  \033[1;31m• Netzwerkverbindung wird initialisiert... Bitte Netzwerkkabel prüfen.\033[0m")

    lines.extend([
        "",
        "================================================================================",
        "\033[0m",
    ])
    return "\n".join(lines)


def write_to_system_banners() -> None:
    banner = format_banner()

    # 1. Print directly to console stdout
    print(banner)

    # 2. Write to /etc/issue (pre-login prompt on physical screens)
    try:
        issue_path = Path("/etc/issue")
        if issue_path.exists() or os.access("/etc", os.W_OK):
            clean_banner = banner.replace("\033[1;36m", "").replace("\033[0m", "").replace("\033[1;32m", "").replace("\033[1;33m", "").replace("\033[1;37m", "").replace("\033[1;31m", "")
            issue_path.write_text(clean_banner + "\n\nDebian GNU/Linux NodeOS \\n \\l\n\n", encoding="utf-8")
    except Exception:
        pass


if __name__ == "__main__":
    write_to_system_banners()
