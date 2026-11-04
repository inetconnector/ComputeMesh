#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""ComputeMesh Windows Service Management & Headless Daemon Engine.

Provides full Windows Service Control Manager (SCM) lifecycle support:
- Service installation (sc.exe create ComputeMeshNode ...)
- Service uninstallation (sc.exe delete ComputeMeshNode)
- Service start / stop / status query
- Robust headless execution loop for background GPU inference & telemetry
"""
from __future__ import annotations

import argparse
import os
import subprocess
import sys
import threading
import time
from datetime import UTC, datetime
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

SERVICE_NAME = "ComputeMeshNode"
SERVICE_DISPLAY_NAME = "ComputeMesh AI Provider Service"
SERVICE_DESCRIPTION = "ComputeMesh Windows GPU Provider Node, RPC-Inference & Local Web Dashboard Server."


def _log(msg: str) -> None:
    try:
        log_dir = Path.home() / ".computemesh"
        log_dir.mkdir(parents=True, exist_ok=True)
        with open(log_dir / "service.log", "a", encoding="utf-8") as f:
            f.write(f"[{datetime.now(UTC).isoformat()}] {msg}\n")
    except Exception:
        pass
    print(f"[{SERVICE_NAME}] {msg}")


def install_service(exe_path: str | None = None) -> bool:
    """Register ComputeMesh as an official Windows Service via sc.exe."""
    if sys.platform != "win32":
        print("[!] Windows Service installation is only supported on Windows.")
        return False

    if not exe_path:
        if getattr(sys, "frozen", False):
            target = f'"{sys.executable}" --service'
        else:
            tray_script = REPO_ROOT / "tools" / "appliance" / "windows_tray_app.py"
            target = f'"{sys.executable}" "{tray_script}" --service'
    else:
        target = f'"{exe_path}" --service'

    try:
        # Create service
        cmd_create = [
            "sc.exe", "create", SERVICE_NAME,
            f"binPath= {target}",
            "start= auto",
            f"DisplayName= {SERVICE_DISPLAY_NAME}",
        ]
        res = subprocess.run(cmd_create, capture_output=True, text=True, check=False)
        if res.returncode != 0 and "exists" not in res.stderr.lower():
            _log(f"Service creation failed: {res.stderr or res.stdout}")
            return False

        # Set service description
        cmd_desc = ["sc.exe", "description", SERVICE_NAME, SERVICE_DESCRIPTION]
        subprocess.run(cmd_desc, capture_output=True, check=False)

        # Set restart on failure
        cmd_failure = ["sc.exe", "failure", SERVICE_NAME, "reset= 86400", "actions= restart/5000/restart/10000/restart/20000"]
        subprocess.run(cmd_failure, capture_output=True, check=False)

        _log(f"Successfully registered Windows Service '{SERVICE_NAME}'.")
        return True
    except Exception as exc:
        _log(f"Failed to install service: {exc}")
        return False


def uninstall_service() -> bool:
    """Unregister and remove the Windows Service via sc.exe."""
    if sys.platform != "win32":
        return False
    try:
        stop_service()
        res = subprocess.run(["sc.exe", "delete", SERVICE_NAME], capture_output=True, text=True, check=False)
        if res.returncode == 0:
            _log(f"Successfully removed Windows Service '{SERVICE_NAME}'.")
            return True
        else:
            _log(f"Service deletion returned: {res.stderr or res.stdout}")
            return False
    except Exception as exc:
        _log(f"Failed to uninstall service: {exc}")
        return False


def start_service() -> bool:
    """Start the registered Windows Service."""
    if sys.platform != "win32":
        return False
    try:
        res = subprocess.run(["sc.exe", "start", SERVICE_NAME], capture_output=True, text=True, check=False)
        return res.returncode == 0
    except Exception as exc:
        _log(f"Failed to start service: {exc}")
        return False


def stop_service() -> bool:
    """Stop the registered Windows Service."""
    if sys.platform != "win32":
        return False
    try:
        res = subprocess.run(["sc.exe", "stop", SERVICE_NAME], capture_output=True, text=True, check=False)
        return res.returncode == 0
    except Exception as exc:
        _log(f"Failed to stop service: {exc}")
        return False


def query_service_status() -> dict[str, str]:
    """Query the current state of the Windows Service."""
    if sys.platform != "win32":
        return {"status": "UNSUPPORTED_PLATFORM"}
    try:
        res = subprocess.run(["sc.exe", "query", SERVICE_NAME], capture_output=True, text=True, check=False)
        out = res.stdout.upper()
        if "RUNNING" in out:
            return {"status": "RUNNING", "installed": "true"}
        elif "STOPPED" in out:
            return {"status": "STOPPED", "installed": "true"}
        elif "PAUSED" in out:
            return {"status": "PAUSED", "installed": "true"}
        elif "1060" in out or "NOT_FOUND" in out or "FAILED" in out:
            return {"status": "NOT_INSTALLED", "installed": "false"}
        return {"status": "UNKNOWN", "raw": res.stdout}
    except Exception as exc:
        return {"status": "ERROR", "error": str(exc)}


def run_headless_daemon() -> int:
    """Runs the headless background daemon executing all node server and telemetry tasks."""
    _log("Starting ComputeMesh Headless Windows Provider Daemon...")
    from tools.appliance.hardware_detector import scan_rig_hardware_stable
    from tools.appliance.appliance_config import load_appliance_config
    from services.appliance_dashboard.server import create_dashboard_server
    from services.appliance_dashboard.tunnel_relay import get_default_node_id
    from tools.appliance.lan_discovery_responder import start_lan_discovery_responder

    # Scan hardware
    inventory = scan_rig_hardware_stable()
    cfg = load_appliance_config()
    node_id = getattr(cfg, "rig_name", "") or getattr(cfg, "node_id", "") or get_default_node_id()

    # Start dashboard server on 0.0.0.0:8080
    server, actual_port = create_dashboard_server(
        host="0.0.0.0",
        port=8080,
        config=cfg,
        inventory=inventory,
        node_id=node_id,
    )
    http_thread = threading.Thread(target=server.serve_forever, daemon=True)
    http_thread.start()
    _log(f"Dashboard server active on http://0.0.0.0:{actual_port}/")

    # Start LAN discovery responder
    gpu_desc = inventory.gpus[0].model_name if getattr(inventory, "gpus", None) else "Windows AI Node"
    try:
        start_lan_discovery_responder(node_id=node_id, port=actual_port, gpu_summary=gpu_desc)
        _log(f"LAN discovery active on UDP 13379 for node {node_id}")
    except Exception as e:
        _log(f"LAN discovery start skipped: {e}")

    # Start Cloud Tunnel Relay (Heartbeat & Remote Workspace Sync)
    try:
        from services.appliance_dashboard.tunnel_relay import start_cloud_tunnel_relay
        relay = start_cloud_tunnel_relay(node_id=node_id)
        _log(f"Cloud tunnel relay active for node {node_id}")
    except Exception as e:
        _log(f"Cloud tunnel relay start warning: {e}")

    # Keep alive loop
    try:
        while True:
            time.sleep(1.0)
    except (KeyboardInterrupt, SystemExit):
        _log("Daemon stopping on signal...")
        try:
            server.shutdown()
        except Exception:
            pass
        return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="ComputeMesh Windows Service Manager")
    parser.add_argument("--install", action="store_true", help="Install Windows Service")
    parser.add_argument("--uninstall", action="store_true", help="Uninstall Windows Service")
    parser.add_argument("--start", action="store_true", help="Start Windows Service")
    parser.add_argument("--stop", action="store_true", help="Stop Windows Service")
    parser.add_argument("--status", action="store_true", help="Query Windows Service status")
    parser.add_argument("--run-daemon", action="store_true", help="Run background daemon directly")
    args = parser.parse_args()

    if args.install:
        return 0 if install_service() else 1
    elif args.uninstall:
        return 0 if uninstall_service() else 1
    elif args.start:
        return 0 if start_service() else 1
    elif args.stop:
        return 0 if stop_service() else 1
    elif args.status:
        st = query_service_status()
        print(f"Service status: {st.get('status', 'UNKNOWN')}")
        return 0
    elif args.run_daemon:
        return run_headless_daemon()
    else:
        parser.print_help()
        return 0


if __name__ == "__main__":
    sys.exit(main())
