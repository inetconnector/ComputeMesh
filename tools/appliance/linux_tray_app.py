#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""ComputeMesh Linux Desktop Provider App & Background Daemon (Debian/Ubuntu).

Completely replaces legacy Tkinter UI with a modern, professional architecture:
- Headless systemd Service daemon & local Web Dashboard engine (Port 8080)
- Google AI Studio style web interface accessible via browser
- Native Linux System Tray icon (via pystray / AppIndicator) with 1-Click browser launch
- Single-instance file-lock enforcement (second launch pops up the web dashboard and exits cleanly)
- Multi-GPU Telemetry (NVIDIA CUDA, AMD ROCm/Vulkan, Intel SYCL), Token Metering & Fleet Heartbeats
- Zero Tkinter dependencies, zero X11/Tk crash risks
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import threading
import time
import urllib.request
import webbrowser
from datetime import UTC, datetime
from pathlib import Path

if getattr(sys, "frozen", False):
    REPO_ROOT = Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent))
else:
    REPO_ROOT = Path(__file__).resolve().parents[2]

if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from config import CONFIG
from services.appliance_dashboard.server import create_dashboard_server
from services.updater.auto_updater import AutoUpdater
from tools.appliance.appliance_config import load_appliance_config
from tools.appliance.hardware_detector import scan_rig_hardware_stable

try:
    from PIL import Image, ImageDraw
    HAS_PIL = True
except ImportError:
    Image = None
    ImageDraw = None
    HAS_PIL = False

try:
    import pystray
    HAS_PYSTRAY = True
except (ImportError, OSError, ValueError, TypeError, KeyError, AttributeError, IndexError, RuntimeError):
    HAS_PYSTRAY = False

AUTOSTART_DESKTOP_FILE = Path.home() / ".config" / "autostart" / "computemesh.desktop"
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


def _create_computemesh_icon_image(size: tuple[int, int] = (64, 64)) -> Image.Image | None:
    """Generates a branded high-res ComputeMesh cyan mesh icon image with PIL."""
    if not HAS_PIL:
        return None
    w, h = size
    img = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    pad = max(2, w // 16)
    draw.ellipse((pad, pad, w - pad, h - pad), fill=(19, 19, 20, 255), outline=(0, 229, 255, 255), width=max(1, w // 16))
    cw, ch = w // 2, h // 2
    cr = max(2, w // 6)
    draw.ellipse((cw - cr, ch - cr, cw + cr, ch + cr), fill=(0, 229, 255, 255))
    r_node = max(1, w // 12)
    dist = w // 3
    nodes = [(cw, ch - dist), (cw + dist, ch), (cw, ch + dist), (cw - dist, ch)]
    for nx, ny in nodes:
        draw.line([(cw, ch), (nx, ny)], fill=(138, 180, 248, 255), width=max(1, w // 16))
        draw.ellipse((nx - r_node, ny - r_node, nx + r_node, ny + r_node), fill=(0, 229, 255, 255))
    return img


def _find_icon() -> Path | None:
    candidates = [
        Path(getattr(sys, "_MEIPASS", ".")) / "tools" / "appliance" / "computemesh.png",
        Path(getattr(sys, "_MEIPASS", ".")) / "computemesh.png",
        Path(__file__).resolve().parent / "computemesh.png",
        REPO_ROOT / "portal" / "assets" / "computemesh.png",
        Path.cwd() / "computemesh.png",
        REPO_ROOT / "tools" / "appliance" / "computemesh.ico",
    ]
    for p in candidates:
        if p.exists():
            return p
    return None


def _log_event(msg: str) -> None:
    try:
        log_dir = Path.home() / ".computemesh"
        log_dir.mkdir(parents=True, exist_ok=True)
        with open(log_dir / "app_debug.log", "a", encoding="utf-8") as f:
            f.write(f"[{datetime.now(UTC).isoformat()}] {msg}\n")
    except Exception:
        pass


_SINGLE_INSTANCE_LOCK_FD: int | None = None


def _acquire_single_instance_lock() -> bool:
    """Enforce strict single-instance execution using POSIX fcntl.flock on ~/.computemesh/app.lock."""
    global _SINGLE_INSTANCE_LOCK_FD
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
            # Already running: pop up dashboard in default browser and exit
            _log_event("Secondary instance launched: opening web dashboard in browser and exiting.")
            webbrowser.open(f"http://localhost:{get_active_dashboard_port()}/agent")
            return False
        _SINGLE_INSTANCE_LOCK_FD = lock_fd
        return True
    except Exception as e:
        # On platforms without fcntl (e.g. Windows during cross-platform testing)
        _log_event(f"Lock acquire fallback: {e}")
        return True


def is_linux_autostart_enabled() -> bool:
    """Check if autostart desktop entry exists in ~/.config/autostart/."""
    return AUTOSTART_DESKTOP_FILE.exists()


def set_linux_autostart(enable: bool) -> bool:
    """Enable or disable Linux autostart desktop entry."""
    try:
        if enable:
            AUTOSTART_DESKTOP_FILE.parent.mkdir(parents=True, exist_ok=True)
            exec_cmd = sys.executable if getattr(sys, "frozen", False) else f"{sys.executable} {Path(__file__).resolve()}"
            content = f"""[Desktop Entry]
Type=Application
Name=ComputeMesh Provider Node
Exec={exec_cmd} --tray
Icon=computemesh
Terminal=false
Categories=Utility;Network;
X-GNOME-Autostart-enabled=true
"""
            AUTOSTART_DESKTOP_FILE.write_text(content, encoding="utf-8")
        else:
            if AUTOSTART_DESKTOP_FILE.exists():
                AUTOSTART_DESKTOP_FILE.unlink()
        return True
    except Exception as exc:
        _log_event(f"Autostart toggle failed: {exc}")
        return False


def resolve_headless_node_id(cfg: object) -> str:
    configured = str(getattr(cfg, "rig_name", "") or "").strip()
    if configured and configured != "test-node-custom":
        return configured
    from services.appliance_dashboard.tunnel_relay import get_default_node_id
    return get_default_node_id()


class LinuxComputeMeshProviderApp:
    """Clean, headless & System-Tray enabled ComputeMesh Linux Provider App."""

    def __init__(self, owner_key: str | None = None) -> None:
        self.version = CONFIG.appliance_version
        self.dashboard_port = DEFAULT_DASHBOARD_PORT
        self.updater = AutoUpdater(current_version=self.version)
        self.owner_key = owner_key
        self.is_running = True
        self.total_tokens_served = 0
        self.total_earnings_usd = 0.00
        self.inventory = scan_rig_hardware_stable()
        self.tray_icon = None
        self._stop_event = threading.Event()

        # Resolve icon
        icon_path = _find_icon()
        if icon_path and icon_path.exists() and HAS_PIL:
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

    def _start_lan_discovery(self) -> None:
        try:
            from services.appliance_dashboard.tunnel_relay import get_default_node_id
            from tools.appliance.lan_discovery_responder import start_lan_discovery_responder
            cfg = load_appliance_config()
            nid = getattr(cfg, "rig_name", "") or getattr(cfg, "node_id", "") or get_default_node_id()
            gpu_desc = self.inventory.gpus[0].model_name if getattr(self.inventory, "gpus", None) else "Linux AI Node"
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
        return round(tf if tf > 0 else 14.5, 1)

    def _run_embedded_server(self) -> None:
        log_file = Path.home() / ".computemesh" / "app_debug.log"
        try:
            log_file.parent.mkdir(parents=True, exist_ok=True)
            cfg = load_appliance_config()
            nid = resolve_headless_node_id(cfg)
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
            try:
                gpu_desc = self.inventory.gpus[0].model_name if getattr(self.inventory, "gpus", None) else "Linux AI Node"
                from tools.appliance.lan_discovery_responder import start_lan_discovery_responder
                start_lan_discovery_responder(
                    node_id=nid,
                    port=actual_port,
                    gpu_summary=f"{gpu_desc} ({self._calculate_local_tflops()} TFLOPS)",
                )
            except Exception:
                pass
            with open(log_file, "a", encoding="utf-8") as f:
                f.write(f"[{datetime.now(UTC).isoformat()}] Dashboard server listening on http://0.0.0.0:{actual_port}\n")
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
                    _log_event(f"AutoUpdater: New version {update_info.version} available.")
            except Exception as e:
                _log_event(f"AutoUpdater error: {e}")
            time.sleep(600)

    def open_web_dashboard(self, *args) -> None:
        """Opens the local ComputeMesh Node Dashboard in the default browser."""
        webbrowser.open(f"http://localhost:{self.dashboard_port}/")

    def open_agent_studio(self, *args) -> None:
        """Opens the Agent Workspace in the default browser."""
        webbrowser.open(f"http://localhost:{self.dashboard_port}/agent")

    def open_chat_studio(self, *args) -> None:
        """Opens the Local Chat Studio in the default browser."""
        webbrowser.open(f"http://localhost:{self.dashboard_port}/webui/")

    def open_fleet_portal(self, *args) -> None:
        """Opens the official ComputeMesh Fleet Cockpit (authenticated securely via loopback/session)."""
        webbrowser.open("https://mesh.inetconnector.com/fleet")

    def toggle_autostart(self, icon=None, item=None) -> None:
        current = is_linux_autostart_enabled()
        set_linux_autostart(not current)

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
        """Runs the taskbar notification tray icon via pystray."""
        if not HAS_PYSTRAY or self.icon_image is None:
            _log_event("pystray unavailable or headless: running in headless daemon mode.")
            self._stop_event.wait()
            return

        def autostart_checked(item):
            return is_linux_autostart_enabled()

        gpu_name = self.inventory.gpus[0].model_name if getattr(self.inventory, "gpus", None) else "Linux AI Node"

        menu = pystray.Menu(
            pystray.MenuItem("✨ ComputeMesh Studio & Dashboard", self.open_web_dashboard, default=True),
            pystray.MenuItem("🤖 Agent Workspace (/agent)", self.open_agent_studio),
            pystray.MenuItem("💬 AI Chat Studio (/webui/)", self.open_chat_studio),
            pystray.MenuItem("🌐 Flotten-Cockpit (mesh.inetconnector.com)", self.open_fleet_portal),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem(f"🖥️ GPU: {gpu_name}", lambda item: self.open_web_dashboard()),
            pystray.MenuItem("🚀 Linux Autostart", self.toggle_autostart, checked=autostart_checked),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("⏹️ ComputeMesh beenden", self.quit_app),
        )

        self.tray_icon = pystray.Icon(
            "ComputeMesh",
            self.icon_image,
            f"ComputeMesh Studio — {gpu_name} (Port {self.dashboard_port})",
            menu=menu,
        )
        _log_event("Linux System Tray Icon initialized successfully.")
        self.tray_icon.run()


def main() -> int:
    parser = argparse.ArgumentParser(description="ComputeMesh Linux Provider Node & Web Studio")
    parser.add_argument("--tray", action="store_true", help="Start minimized in system tray")
    parser.add_argument("--service", action="store_true", help="Run headless as background service")
    parser.add_argument("--run-daemon", action="store_true", help="Run headless as background daemon")
    parser.add_argument("--owner-key", type=str, default=None, help="Owner fleet key")
    args, unknown = parser.parse_known_args()

    # Single-instance enforcement
    if not _acquire_single_instance_lock():
        sys.exit(0)

    try:
        app = LinuxComputeMeshProviderApp(owner_key=args.owner_key)

        # Unless started with --tray or --service/--run-daemon, immediately pop up web dashboard
        if not args.tray and not args.service and not args.run_daemon:
            app.open_web_dashboard()

        # If headless service mode requested
        if args.service or args.run_daemon:
            _log_event("Running in headless Linux Service mode.")
            app._stop_event.wait()
            return 0

        # Run tray loop
        app.run_tray()
    except (KeyboardInterrupt, SystemExit):
        return 0
    except Exception as exc:
        _log_event(f"Fatal error in Linux provider app: {exc}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
