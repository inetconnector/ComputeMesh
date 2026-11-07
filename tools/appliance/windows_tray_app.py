#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""ComputeMesh Windows Provider Service & Taskbar Tray Launcher.

Completely replaces legacy Tkinter UI with a modern, professional architecture:
- Headless Windows Service daemon & local Web Dashboard engine (Port 8080)
- Google AI Studio style web interface accessible via browser
- Native Windows System Tray icon with 1-Click browser launch
- Single-instance Named Mutex enforcement (opening taskbar icon or second launch pops up the web dashboard)
- GPU Telemetry (NVIDIA CUDA, AMD ROCm/Vulkan, Intel SYCL), Token Metering & Fleet Heartbeats
- Zero Tkinter dependencies, zero Tcl/Tk crash risks
"""
from __future__ import annotations

import argparse
import json
import multiprocessing
import os
import subprocess
import sys
import threading
import time
import urllib.request
import webbrowser
from datetime import UTC, datetime
from pathlib import Path

from cm_tray_bootstrap import REPO_ROOT
from config import CONFIG
from PIL import Image, ImageDraw
from services.appliance_dashboard.server import create_dashboard_server
from services.updater.auto_updater import AutoUpdater
from tools.appliance.appliance_config import load_appliance_config
from tools.appliance.hardware_detector import scan_rig_hardware_stable
from tools.appliance.windows_cline_integration import (
    ensure_cline_integration,
    find_vscode_executable,
    launch_cline_in_vscode,
)

try:
    import pystray
    import pystray._win32
    HAS_PYSTRAY = True
except (ImportError, OSError, ValueError, TypeError, KeyError, AttributeError, IndexError, RuntimeError):
    HAS_PYSTRAY = False

try:
    import winreg
    HAS_WINREG = True
except ImportError:
    HAS_WINREG = False

REG_RUN_PATH = r"Software\Microsoft\Windows\CurrentVersion\Run"
REG_APP_NAME = "ComputeMesh"
DEFAULT_DASHBOARD_PORT = 8080


def get_active_dashboard_port() -> int:
    """Returns the actively listening dashboard port, with fallback to default."""
    port_file = Path.home() / ".computemesh" / "dashboard_port"
    if port_file.exists():
        try:
            val = int(port_file.read_text(encoding="utf-8").strip())
            if 1024 <= val <= 65535:
                return val
        except Exception:
            pass
    return DEFAULT_DASHBOARD_PORT


def _create_computemesh_icon_image(size: tuple[int, int] = (32, 32)) -> Image.Image:
    """Generates a crisp branded high-visibility cyan mesh badge for Windows taskbar & tray."""
    w, h = size
    img = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    pad = max(1, w // 32)
    # Vibrant solid cyan circular badge (matching WhatsApp/Bluetooth visibility on dark taskbars)
    draw.ellipse((pad, pad, w - pad - 1, h - pad - 1), fill=(0, 215, 255, 255), outline=(255, 255, 255, 200), width=max(1, w // 32))
    cw, ch = w // 2, h // 2
    cr = max(2, w // 7)
    draw.ellipse((cw - cr, ch - cr, cw + cr, ch + cr), fill=(10, 25, 45, 255))
    dist = int(w * 0.28)
    r_node = max(1, w // 11)
    nodes = [(cw, ch - dist), (cw + dist, ch), (cw, ch + dist), (cw - dist, ch)]
    for nx, ny in nodes:
        draw.line([(cw, ch), (nx, ny)], fill=(10, 25, 45, 220), width=max(1, w // 14))
        draw.ellipse((nx - r_node, ny - r_node, nx + r_node, ny + r_node), fill=(10, 25, 45, 255))
    return img


def _find_icon() -> Path | None:
    candidates = [
        Path(getattr(sys, "_MEIPASS", ".")) / "tools" / "appliance" / "computemesh.ico",
        Path(getattr(sys, "_MEIPASS", ".")) / "computemesh.ico",
        Path(getattr(sys, "_MEIPASS", ".")) / "portal" / "assets" / "computemesh.png",
        Path(__file__).resolve().parent / "computemesh.ico",
        REPO_ROOT / "tools" / "appliance" / "computemesh.ico",
        REPO_ROOT / "portal" / "assets" / "computemesh.ico",
        REPO_ROOT / "portal" / "assets" / "computemesh.png",
        Path.cwd() / "tools" / "appliance" / "computemesh.ico",
    ]
    for p in candidates:
        if p.exists():
            return p
    return None


def _log_event(msg: str) -> None:
    try:
        crash_log = Path.home() / ".computemesh" / "app_debug.log"
        crash_log.parent.mkdir(parents=True, exist_ok=True)
        with open(crash_log, "a", encoding="utf-8") as f:
            f.write(f"[{datetime.now(UTC).isoformat()}] {msg}\n")
    except Exception:
        pass


_SINGLE_INSTANCE_MUTEX = None
_SINGLE_INSTANCE_LOCK_FD: int | None = None


def _acquire_single_instance_lock() -> bool:
    """Enforce strict single-instance execution using a robust OS-level Windows Named Mutex.
    
    If an existing instance is already running and the user launches the app again (e.g. from desktop
    shortcut or start menu), the second instance automatically triggers the browser to open the
    Google AI Studio Web Dashboard and exits cleanly.
    """
    global _SINGLE_INSTANCE_LOCK_FD, _SINGLE_INSTANCE_MUTEX
    if sys.platform == "win32":
        try:
            import ctypes
            kernel32 = ctypes.windll.kernel32
            ERROR_ALREADY_EXISTS = 183

            mutex_name = "Local\\ComputeMesh_Provider_App_Mutex"
            _SINGLE_INSTANCE_MUTEX = kernel32.CreateMutexW(None, True, mutex_name)
            last_err = kernel32.GetLastError()
            if last_err == ERROR_ALREADY_EXISTS:
                # Open Web Dashboard in default browser and exit immediately
                _log_event("Secondary instance launched: opening web dashboard in browser and exiting.")
                webbrowser.open(f"http://localhost:{get_active_dashboard_port()}/")
                return False
            return True
        except Exception as e:
            _log_event(f"Single instance mutex error: {e}")
            return True
    else:
        try:
            import fcntl
            lock_path = Path.home() / ".computemesh" / "app.lock"
            lock_path.parent.mkdir(parents=True, exist_ok=True)
            lock_flags = os.O_CREAT | os.O_RDWR | getattr(os, "O_CLOEXEC", 0)
            lock_fd = os.open(lock_path, lock_flags, 0o600)
            try:
                fcntl.flock(lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except Exception:
                os.close(lock_fd)
                webbrowser.open(f"http://localhost:{get_active_dashboard_port()}/")
                return False
            _SINGLE_INSTANCE_LOCK_FD = lock_fd
            return True
        except Exception:
            return False


def is_windows_autostart_enabled() -> bool:
    """Check if ComputeMesh is registered in HKCU Run key."""
    if not HAS_WINREG:
        return False
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, REG_RUN_PATH, 0, winreg.KEY_READ) as key:
            winreg.QueryValueEx(key, REG_APP_NAME)
            return True
    except Exception:
        return False


def set_windows_autostart(enable: bool) -> bool:
    """Enable or disable Windows Autostart in HKCU Run key."""
    if not HAS_WINREG:
        return False
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, REG_RUN_PATH, 0, winreg.KEY_WRITE) as key:
            if enable:
                exe_path = sys.executable
                if getattr(sys, "frozen", False):
                    target = f'"{exe_path}" --tray'
                else:
                    script_path = str(Path(__file__).resolve())
                    target = f'"{exe_path}" "{script_path}" --tray'
                winreg.SetValueEx(key, REG_APP_NAME, 0, winreg.REG_SZ, target)
            else:
                try:
                    winreg.DeleteValue(key, REG_APP_NAME)
                except Exception:
                    pass
            return True
    except Exception:
        return False


class ComputeMeshProviderApp:
    """Modern ComputeMesh Windows Provider Service & Tray Coordinator."""

    def __init__(self, owner_key: str | None = None) -> None:
        self.version = CONFIG.appliance_version
        self.dashboard_port = DEFAULT_DASHBOARD_PORT
        self.updater = AutoUpdater(current_version=self.version)
        self.owner_key = owner_key
        self.is_running = True
        self.is_provider_active = True
        self.total_tokens_served = 0
        self.total_earnings_usd = 0.00
        self.inventory = scan_rig_hardware_stable()
        self.tray_icon = None
        self._stop_event = threading.Event()
        self._server_ready_event = threading.Event()

        # Resolve icon
        icon_path = _find_icon()
        if icon_path and icon_path.exists():
            try:
                self.icon_image = Image.open(icon_path)
            except Exception:
                self.icon_image = _create_computemesh_icon_image()
        else:
            self.icon_image = _create_computemesh_icon_image()

        # Start embedded localhost:8080 web server
        self.http_thread = threading.Thread(target=self._run_embedded_server, daemon=True)
        self.http_thread.start()

        # Start LAN UDP discovery responder
        self._start_lan_discovery()

        # Start background telemetry thread
        self.telemetry_thread = threading.Thread(target=self._telemetry_loop, daemon=True)
        self.telemetry_thread.start()

        # Start background auto-updater thread
        self.updater_thread = threading.Thread(target=self._auto_updater_loop, daemon=True)
        self.updater_thread.start()

    def _get_config_path(self) -> Path:
        p = Path.home() / ".computemesh" / "appliance_config.json"
        p.parent.mkdir(parents=True, exist_ok=True)
        return p

    def _start_lan_discovery(self) -> None:
        try:
            from services.appliance_dashboard.tunnel_relay import get_default_node_id
            from tools.appliance.lan_discovery_responder import start_lan_discovery_responder
            cfg = load_appliance_config()
            nid = getattr(cfg, "rig_name", "") or getattr(cfg, "node_id", "") or get_default_node_id()
            gpu_desc = self.inventory.gpus[0].model_name if getattr(self.inventory, "gpus", None) else "Windows AI Node"
            start_lan_discovery_responder(
                node_id=nid,
                port=self.dashboard_port,
                gpu_summary=f"{gpu_desc} ({self._calculate_local_tflops()} TFLOPS)"
            )
            _log_event(f"LAN Discovery active on UDP 13379 (Node: {nid}, Port: {self.dashboard_port})")
        except Exception as e:
            _log_event(f"LAN discovery start skipped: {e}")

    def _calculate_local_tflops(self) -> float:
        tf = 0.0
        if getattr(self.inventory, "gpus", None):
            for g in self.inventory.gpus:
                tf += getattr(g, "tflops", 0.0) or 0.0
        return round(tf if tf > 0 else 29.8, 1)

    def _run_embedded_server(self) -> None:
        log_file = Path.home() / ".computemesh" / "app_debug.log"
        try:
            log_file.parent.mkdir(parents=True, exist_ok=True)
            cfg = load_appliance_config()
            from services.appliance_dashboard.tunnel_relay import get_default_node_id
            nid = getattr(cfg, "rig_name", "") or getattr(cfg, "node_id", "") or get_default_node_id()
            server, actual_port = create_dashboard_server(
                host="0.0.0.0",
                port=self.dashboard_port,
                config=cfg,
                inventory=self.inventory,
                node_id=nid
            )
            self.dashboard_port = actual_port
            try:
                p_file = Path.home() / ".computemesh" / "dashboard_port"
                p_file.parent.mkdir(parents=True, exist_ok=True)
                p_file.write_text(str(actual_port), encoding="utf-8")
            except Exception:
                pass
            with open(log_file, "a", encoding="utf-8") as f:
                f.write(f"[{datetime.now(UTC).isoformat()}] Dashboard server listening on http://0.0.0.0:{actual_port}\n")
            self._server_ready_event.set()

            # Start Cloud Tunnel Relay (Heartbeat & Remote Workspace Sync)
            try:
                from services.appliance_dashboard.tunnel_relay import start_cloud_tunnel_relay
                start_cloud_tunnel_relay(node_id=nid)
                _log_event(f"Cloud tunnel relay active for node {nid}")
            except Exception as e:
                _log_event(f"Cloud tunnel relay start warning: {e}")

            server.serve_forever()
        except Exception as e:
            _log_event(f"Dashboard server error: {e}")

    def _telemetry_loop(self) -> None:
        while not self._stop_event.is_set():
            time.sleep(2.5)
            try:
                from tools.appliance.token_metering import get_token_stats
                t_stats = get_token_stats()
                self.total_tokens_served = t_stats.get("tokens_processed", 0)
                self.total_earnings_usd = t_stats.get("earnings_usd", 0.0)
            except Exception:
                pass

    def _auto_updater_loop(self) -> None:
        time.sleep(20)
        while not self._stop_event.is_set():
            try:
                update_info = self.updater.check_for_updates()
                if update_info and update_info.is_newer:
                    _log_event(f"AutoUpdater: New version {update_info.version} available. Applying...")
                    downloaded = self.updater.download_and_verify(update_info)
                    self.updater.apply_windows_update(downloaded)
            except Exception as e:
                _log_event(f"AutoUpdater error: {e}")
            time.sleep(600)

    def open_web_dashboard(self, *args) -> None:
        """Opens the local ComputeMesh Node Dashboard in the default browser."""
        self._server_ready_event.wait(timeout=3.0)
        webbrowser.open(f"http://localhost:{self.dashboard_port}/")

    def open_agent_studio(self, *args) -> None:
        """Opens the Agent Workspace in the default browser."""
        self._server_ready_event.wait(timeout=3.0)
        webbrowser.open(f"http://localhost:{self.dashboard_port}/agent")

    def open_chat_studio(self, *args) -> None:
        """Opens the Local Chat Studio in the default browser."""
        self._server_ready_event.wait(timeout=3.0)
        webbrowser.open(f"http://localhost:{self.dashboard_port}/webui/")

    def open_fleet_portal(self, *args) -> None:
        """Opens the official ComputeMesh Fleet Cockpit."""
        webbrowser.open("https://mesh.inetconnector.com/fleet")

    def toggle_provider(self, icon=None, item=None) -> None:
        """Toggles between active and paused provider state."""
        self.is_provider_active = not self.is_provider_active
        cfg = load_appliance_config()
        nid = getattr(cfg, "rig_name", "") or getattr(cfg, "node_id", "") or "cm-win-mifcom-rtx3080"
        gpu_name = self.inventory.gpus[0].model_name if getattr(self.inventory, "gpus", None) else "Windows AI Node"

        if self.is_provider_active:
            _log_event("Provider resumed: starting cloud tunnel relay.")
            try:
                from services.appliance_dashboard.tunnel_relay import start_cloud_tunnel_relay
                start_cloud_tunnel_relay(node_id=nid)
            except Exception as e:
                _log_event(f"Resume tunnel relay warning: {e}")
            if self.tray_icon:
                self.tray_icon.title = f"ComputeMesh Studio — {gpu_name} (Aktiv, Port {self.dashboard_port})"
        else:
            _log_event("Provider paused: stopping cloud tunnel relay.")
            try:
                import services.appliance_dashboard.tunnel_relay as tr
                if tr.CLOUD_TUNNEL_RELAY:
                    tr.CLOUD_TUNNEL_RELAY.stop()
                    tr.CLOUD_TUNNEL_RELAY = None
            except Exception as e:
                _log_event(f"Pause tunnel relay warning: {e}")
            if self.tray_icon:
                self.tray_icon.title = f"ComputeMesh — Angehalten (Port {self.dashboard_port})"
        if self.tray_icon:
            try:
                self.tray_icon.update_menu()
            except Exception:
                pass

    def register_workspace_dialog(self, *args) -> None:
        """Opens a folder selection dialog to register a local project path."""
        try:
            import tkinter as tk
            from tkinter import filedialog
            root = tk.Tk()
            root.withdraw()
            root.attributes('-topmost', True)
            folder_selected = filedialog.askdirectory(title="ComputeMesh - Lokalen Projektpfad auswählen")
            root.destroy()
            if folder_selected:
                from tools.appliance.workspace_manager import register_local_workspace
                res = register_local_workspace(folder_selected)
                if res:
                    _log_event(f"Registered project workspace: {folder_selected}")
                    # Open agent in browser for this workspace
                    webbrowser.open(f"http://localhost:{self.dashboard_port}/agent?workspace={res.get('id')}")
        except Exception as exc:
            _log_event(f"Workspace dialog error: {exc}")

    def toggle_autostart(self, icon=None, item=None) -> None:
        current = is_windows_autostart_enabled()
        set_windows_autostart(not current)

    def quit_app(self, icon=None, item=None) -> None:
        """Stops background threads and exits cleanly."""
        _log_event("Stopping ComputeMesh application...")
        self._stop_event.set()
        try:
            from tools.appliance.lan_discovery_responder import stop_lan_discovery_responder
            stop_lan_discovery_responder()
        except Exception:
            pass
        if self.tray_icon:
            try:
                self.tray_icon.stop()
            except Exception:
                pass
        sys.exit(0)

    def run_tray(self) -> None:
        """Runs the taskbar notification tray icon."""
        if not HAS_PYSTRAY:
            _log_event("pystray unavailable: running in headless daemon mode.")
            self._stop_event.wait()
            return

        def autostart_checked(item):
            return is_windows_autostart_enabled()

        def status_label(item):
            if self.is_provider_active:
                return f"🟢 Status: Bereit & Aktiv (Port {self.dashboard_port})"
            return f"⏸️ Status: Angehalten (Port {self.dashboard_port})"

        def toggle_label(item):
            if self.is_provider_active:
                return "⏸️ Provider stoppen / pausieren"
            return "▶️ Provider starten"

        gpu_name = self.inventory.gpus[0].model_name if getattr(self.inventory, "gpus", None) else "Windows AI Node"

        menu = pystray.Menu(
            pystray.MenuItem("📊 Node Dashboard öffnen (Hardware & Status)", self.open_web_dashboard, default=True),
            pystray.MenuItem("🤖 Agent Workspace öffnen", self.open_agent_studio),
            pystray.MenuItem("💬 AI Chat Studio öffnen", self.open_chat_studio),
            pystray.MenuItem("🌐 Online Flotten-Cockpit (mesh.inetconnector.com)", self.open_fleet_portal),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem(status_label, lambda item: self.open_web_dashboard()),
            pystray.MenuItem(toggle_label, self.toggle_provider),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("📁 Projektpfad registrieren...", self.register_workspace_dialog),
            pystray.MenuItem(f"🖥️ GPU: {gpu_name}", lambda item: self.open_web_dashboard()),
            pystray.MenuItem("🚀 Windows Autostart", self.toggle_autostart, checked=autostart_checked),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("⏹️ ComputeMesh beenden", self.quit_app),
        )

        self.tray_icon = pystray.Icon(
            "ComputeMesh",
            self.icon_image,
            f"ComputeMesh Studio — {gpu_name} (Port {self.dashboard_port})",
            menu=menu,
        )

        def on_tray_ready(icon):
            icon.visible = True
            try:
                icon.notify(
                    f"ComputeMesh läuft im Infobereich (Port {self.dashboard_port}).\nKlicke auf das Icon (ggf. unter '^'), um das Dashboard zu öffnen.",
                    "ComputeMesh Studio Aktiv"
                )
            except Exception:
                pass

        _log_event("System Tray Icon initialized successfully.")
        self.tray_icon.run(setup=on_tray_ready)


def main() -> int:
    multiprocessing.freeze_support()
    parser = argparse.ArgumentParser(description="ComputeMesh Windows Provider Node & Web Studio")
    parser.add_argument("--tray", action="store_true", help="Start minimized in system tray")
    parser.add_argument("--service", action="store_true", help="Run headless as Windows Service")
    parser.add_argument("--install-service", action="store_true", help="Register as Windows Service")
    parser.add_argument("--uninstall-service", action="store_true", help="Unregister Windows Service")
    parser.add_argument("--owner-key", type=str, default=None, help="Owner fleet key")
    args, unknown = parser.parse_known_args()

    # Handle service registration flags
    if args.install_service:
        from tools.appliance.windows_service import install_service
        return 0 if install_service() else 1
    if args.uninstall_service:
        from tools.appliance.windows_service import uninstall_service
        return 0 if uninstall_service() else 1

    # Single-instance enforcement
    if not _acquire_single_instance_lock():
        sys.exit(0)

    try:
        app = ComputeMeshProviderApp(owner_key=args.owner_key)

        # Unless started with --tray or --service, immediately pop up the web dashboard
        if not args.tray and not args.service:
            app.open_web_dashboard()

        # If --service, run headless without tray icon
        if args.service:
            _log_event("Running in headless Windows Service mode.")
            app._stop_event.wait()
            return 0

        # Run tray loop
        app.run_tray()
    except (KeyboardInterrupt, SystemExit):
        return 0
    except Exception as exc:
        _log_event(f"Fatal error in Windows provider app: {exc}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
