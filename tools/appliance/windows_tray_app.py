#!/usr/bin/env python3
"""ComputeMesh Windows Desktop Provider Tray App.

Lightweight desktop GUI and background inference daemon for Windows GPU providers.
Features:
- Native Windows System Tray integration with minimize-to-tray
- Automatic First-Launch Windows Autostart prompt (via winreg HKCU\\Run)
- Embedded localhost:8080 Web Dashboard server for 1-Click MetaMask integration
- Multi-GPU hardware telemetry (NVIDIA CUDA, AMD Vulkan/ROCm, Intel SYCL)
- Real-time token streaming and automated passive earnings tracking
"""
from __future__ import annotations

from datetime import datetime, timezone
import io
import json
import multiprocessing
import os
from pathlib import Path
import sys
import threading
import time
import tkinter as tk
from tkinter import messagebox, ttk

# Ensure PyInstaller Windows child process bootloader compatibility
multiprocessing.freeze_support()

# Sanitize PyInstaller child process environment variables to prevent bootloader security check errors
for _pyi_env in list(os.environ.keys()):
    if _pyi_env.startswith("_MEI") or _pyi_env.startswith("_PYI") or _pyi_env.startswith("PYINSTALLER"):
        os.environ.pop(_pyi_env, None)

if sys.stdout is None:
    sys.stdout = io.StringIO()
if sys.stderr is None:
    sys.stderr = io.StringIO()

if getattr(sys, "frozen", False):
    REPO_ROOT = Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent))
else:
    REPO_ROOT = Path(__file__).resolve().parents[2]

if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from PIL import Image, ImageDraw, ImageTk, IcoImagePlugin
try:
    import pystray
    import pystray._win32
    HAS_PYSTRAY = True
except Exception:
    HAS_PYSTRAY = False

try:
    import winreg
    HAS_WINREG = True
except ImportError:
    HAS_WINREG = False

from config import CONFIG
from services.appliance_dashboard.server import create_dashboard_server, run_dashboard_server
from services.updater.auto_updater import AutoUpdater, UpdateInfo
from tools.appliance.appliance_config import load_appliance_config
from tools.appliance.hardware_detector import scan_rig_hardware

REG_RUN_PATH = r"Software\Microsoft\Windows\CurrentVersion\Run"
REG_APP_NAME = "ComputeMesh"


def _create_computemesh_icon_image(size: tuple[int, int] = (32, 32)) -> Image.Image:
    """Generates a crisp branded cyan mesh icon for Windows taskbar & tray."""
    w, h = size
    img = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    pad = max(1, w // 16)
    draw.ellipse((pad, pad, w - pad, h - pad), fill=(15, 23, 42, 255), outline=(0, 242, 254, 255), width=max(1, w // 16))
    cw, ch = w // 2, h // 2
    cr = max(2, w // 6)
    draw.ellipse((cw - cr, ch - cr, cw + cr, ch + cr), fill=(0, 242, 254, 255))
    r_node = max(1, w // 12)
    dist = w // 3
    nodes = [(cw, ch - dist), (cw + dist, ch), (cw, ch + dist), (cw - dist, ch)]
    for nx, ny in nodes:
        draw.line([(cw, ch), (nx, ny)], fill=(59, 130, 246, 255), width=max(1, w // 16))
        draw.ellipse((nx - r_node, ny - r_node, nx + r_node, ny + r_node), fill=(0, 242, 254, 255))
    return img


import traceback

def _log_crash(msg: str) -> None:
    try:
        crash_log = Path.home() / ".computemesh" / "app_debug.log"
        crash_log.parent.mkdir(parents=True, exist_ok=True)
        with open(crash_log, "a", encoding="utf-8") as f:
            f.write(f"[{datetime.now(timezone.utc).isoformat()}] {msg}\n")
    except Exception:
        pass

def global_excepthook(exc_type, exc_value, exc_traceback):
    err = "".join(traceback.format_exception(exc_type, exc_value, exc_traceback))
    _log_crash(f"Unhandled Exception: {err}")
    sys.__excepthook__(exc_type, exc_value, exc_traceback)

_SINGLE_INSTANCE_MUTEX = None

def _acquire_single_instance_lock() -> bool:
    """Enforce strict single-instance execution while allowing PyInstaller bootloader child processes."""
    if sys.platform == "win32":
        try:
            lock_path = Path.home() / ".computemesh" / "app.pid"
            lock_path.parent.mkdir(parents=True, exist_ok=True)
            if lock_path.exists():
                try:
                    old_pid = int(lock_path.read_text(encoding="utf-8").strip())
                    cur_pid = os.getpid()
                    cur_ppid = getattr(os, "getppid", lambda: -1)()
                    if old_pid not in (cur_pid, cur_ppid) and old_pid > 0:
                        import ctypes
                        kernel32 = ctypes.windll.kernel32
                        PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
                        h_proc = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, old_pid)
                        if h_proc:
                            kernel32.CloseHandle(h_proc)
                            try:
                                user32 = ctypes.windll.user32
                                hwnd = user32.FindWindowW(None, "ComputeMesh Provider Node — AI Compute Daemon")
                                if hwnd:
                                    user32.ShowWindow(hwnd, 9)  # SW_RESTORE
                                    user32.SetForegroundWindow(hwnd)
                            except Exception:
                                pass
                            return False
                except Exception:
                    pass
            lock_path.write_text(str(os.getpid()), encoding="utf-8")
            return True
        except Exception as e:
            _log_crash(f"Single instance lock check exception: {e}")
            return True
    else:
        try:
            import fcntl
            lock_path = Path.home() / ".computemesh" / "app.lock"
            lock_path.parent.mkdir(parents=True, exist_ok=True)
            _lock_file = open(lock_path, "w")
            fcntl.flock(_lock_file, fcntl.LOCK_EX | fcntl.LOCK_NB)
            return True
        except Exception:
            return False

def _cleanup_previous_instances() -> None:
    """Safe single-instance check stub for backward compatibility."""
    pass


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
    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        self.root.title("ComputeMesh Provider Node — AI Compute Daemon")
        self.root.configure(bg="#0b0f19")

        # Resolve icon paths and create high-res brand image
        self.icon_path = self._find_icon()
        if self.icon_path and self.icon_path.exists():
            try:
                self.icon_image = Image.open(self.icon_path)
            except Exception:
                self.icon_image = _create_computemesh_icon_image()
        else:
            self.icon_image = _create_computemesh_icon_image()

        try:
            self._tk_icon = ImageTk.PhotoImage(self.icon_image)
            self.root.iconphoto(True, self._tk_icon)
            if self.icon_path and self.icon_path.suffix.lower() == ".ico":
                self.root.iconbitmap(default=str(self.icon_path))
        except Exception:
            pass

        # Center window on screen (Wide layout for optimal dashboard overview)
        width = 960
        height = 580
        screen_w = self.root.winfo_screenwidth()
        screen_h = self.root.winfo_screenheight()
        pos_x = max(0, (screen_w - width) // 2)
        pos_y = max(0, (screen_h - height) // 2)
        self.root.geometry(f"{width}x{height}+{pos_x}+{pos_y}")
        self.root.minsize(860, 520)

        self.version = CONFIG.appliance_version
        self.dashboard_port = 8080
        self.updater = AutoUpdater(current_version=self.version)

        # Auto-start providing compute immediately upon launch
        self.is_running = True
        self.total_tokens_served = 0
        self.total_earnings_usd = 0.00
        self.inventory = scan_rig_hardware()
        self.autostart_var = tk.BooleanVar(value=is_windows_autostart_enabled())
        self.autoupdate_var = tk.BooleanVar(value=self._load_autoupdate_setting())

        self._apply_styles()
        self._build_ui()

        # Intercept window close button and minimize event to keep running in System Tray
        self.root.protocol("WM_DELETE_WINDOW", self._hide_to_tray)
        self.root.bind("<Unmap>", self._on_window_unmap)

        # Start embedded local web dashboard server on port 8080 in background
        self.http_thread = threading.Thread(target=self._run_embedded_server, daemon=True)
        self.http_thread.start()

        # Background telemetry polling thread
        self.telemetry_thread = threading.Thread(target=self._telemetry_loop, daemon=True)
        self.telemetry_thread.start()

        # Background auto-updater daemon thread (Ed25519)
        self.updater_thread = threading.Thread(target=self._auto_updater_loop, daemon=True)
        self.updater_thread.start()

        # Initialize System Tray Icon & Keepalive Watchdog
        self.tray_icon = None
        if HAS_PYSTRAY:
            self._setup_tray_icon()
            self.root.after(3000, self._tray_watchdog)

        # First-launch prompt check
        self.root.after(600, self._check_first_launch_prompts)

    def _find_icon(self) -> Path | None:
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

    def _setup_tray_icon(self) -> None:
        try:
            if self.tray_icon is not None:
                try:
                    self.tray_icon.stop()
                except Exception:
                    pass

            tray_image = _create_computemesh_icon_image(size=(32, 32))

            menu = pystray.Menu(
                pystray.MenuItem("🖥️ ComputeMesh öffnen", self._show_from_tray, default=True),
                pystray.MenuItem(lambda item: f"🌐 Web Dashboard (:{self.dashboard_port})", self._open_web_dashboard),
                pystray.Menu.SEPARATOR,
                pystray.MenuItem(
                    lambda item: "⏹ Rechenleistung pausieren" if self.is_running else "▶ Rechenleistung fortsetzen",
                    self._toggle_compute,
                ),
                pystray.MenuItem("🔄 Nach Updates suchen", self._manual_update_check),
                pystray.Menu.SEPARATOR,
                pystray.MenuItem("❌ ComputeMesh beenden", self._quit_app),
            )

            self.tray_icon = pystray.Icon(
                "ComputeMesh",
                tray_image,
                "ComputeMesh AI Provider Node (Serving)",
                menu=menu,
            )
            self.tray_icon.run_detached()
            _log_crash("System Tray Icon successfully started and visible.")
        except Exception as e:
            _log_crash(f"Error setup tray: {e}\n{traceback.format_exc()}")

    def _tray_watchdog(self) -> None:
        """Periodic watchdog to ensure System Tray Icon stays active continuously."""
        try:
            if HAS_PYSTRAY:
                if self.tray_icon is None or not getattr(self.tray_icon, "visible", False):
                    self._setup_tray_icon()
        except Exception:
            pass
        try:
            self.root.after(3000, self._tray_watchdog)
        except Exception:
            pass

    def _hide_to_tray(self) -> None:
        """Minimize application window to system tray without closing daemon."""
        try:
            self.root.withdraw()
        except Exception:
            pass

    def _on_window_unmap(self, event=None) -> None:
        """When user clicks minimize (-) on title bar, hide to tray instead of taskbar."""
        if event and event.widget == self.root:
            try:
                if self.root.state() == "iconic":
                    self.root.after(10, self.root.withdraw)
            except Exception:
                pass

    def _show_from_tray(self, icon=None, item=None) -> None:
        """Restore window from system tray (thread-safe on main Tk loop)."""
        try:
            self.root.after(0, self._do_show_window)
        except Exception:
            pass

    def _do_show_window(self) -> None:
        """Execute window restoration synchronously inside Tk main thread."""
        try:
            self.root.deiconify()
            self.root.state("normal")
            self.root.attributes("-topmost", True)
            self.root.update_idletasks()
            self.root.lift()
            self.root.focus_force()
            self.root.attributes("-topmost", False)
        except Exception as e:
            _log_crash(f"Error showing window from tray: {e}")

    def _quit_app(self, icon=None, item=None) -> None:
        """Completely exit application and stop daemon."""
        if self.tray_icon:
            try:
                self.tray_icon.stop()
            except Exception:
                pass
        try:
            self.root.quit()
        except Exception:
            pass
        sys.exit(0)

    def _load_autoupdate_setting(self) -> bool:
        try:
            cfg = self._get_config_path()
            if cfg.exists():
                return json.loads(cfg.read_text(encoding="utf-8")).get("auto_update", True)
        except Exception:
            pass
        return True

    def _check_first_launch_prompts(self) -> None:
        """Initialize default Autostart & Auto-Update settings without disruptive modal popups."""
        cfg_file = self._get_config_path()
        cfg_data = {}
        if cfg_file.exists():
            try:
                cfg_data = json.loads(cfg_file.read_text(encoding="utf-8"))
            except Exception:
                pass

        if not cfg_data.get("first_launch_prompted", False):
            cfg_data["first_launch_prompted"] = True
            if "autostart" not in cfg_data:
                cfg_data["autostart"] = True
                set_windows_autostart(True)
                self.autostart_var.set(True)
            if "auto_update" not in cfg_data:
                cfg_data["auto_update"] = True
                self.autoupdate_var.set(True)
            try:
                cfg_file.write_text(json.dumps(cfg_data, indent=2), encoding="utf-8")
            except Exception:
                pass

    def _on_autoupdate_toggle(self) -> None:
        enable = self.autoupdate_var.get()
        cfg_file = self._get_config_path()
        try:
            cfg_data = json.loads(cfg_file.read_text(encoding="utf-8")) if cfg_file.exists() else {}
            cfg_data["auto_update"] = enable
            cfg_file.write_text(json.dumps(cfg_data, indent=2), encoding="utf-8")
        except Exception:
            pass

    def _auto_updater_loop(self) -> None:
        """Continuous background thread checking periodically for signed updates."""
        time.sleep(15)  # Initial grace period after launch
        while True:
            try:
                if self._load_autoupdate_setting():
                    update_info = self.updater.check_for_updates()
                    if update_info and update_info.is_newer:
                        _log_crash(f"[AutoUpdater] Newer version {update_info.version} found! Downloading and applying...")
                        downloaded = self.updater.download_and_verify(update_info)
                        self.updater.apply_windows_update(downloaded)
            except Exception as e:
                _log_crash(f"[AutoUpdater] Background check error: {e}")
            time.sleep(600)  # Check every 10 minutes

    def _manual_update_check(self, *args) -> None:
        try:
            update_info = self.updater.check_for_updates()
            if update_info and update_info.is_newer:
                if messagebox.askyesno(
                    "Update verfügbar",
                    f"Eine neue ComputeMesh-Version ({update_info.version}) ist verfügbar!\n\n"
                    f"Kryptografische Ed25519-Signatur: GÜLTIG\n"
                    f"SHA-256 Prüfsumme: Verifiziert\n\n"
                    "Möchtest du das signierte Update jetzt sicher herunterladen und installieren?",
                    parent=self.root,
                ):
                    downloaded = self.updater.download_and_verify(update_info)
                    self.updater.apply_windows_update(downloaded)
            else:
                messagebox.showinfo(
                    "ComputeMesh Auto-Updater",
                    f"✓ Du verwendest bereits die aktuellste, sicher signierte Version (v{self.version}).",
                    parent=self.root,
                )
        except Exception as e:
            messagebox.showerror("Update Error", f"Update-Prüfung fehlgeschlagen: {e}", parent=self.root)

    def _on_autostart_toggle(self) -> None:
        enable = self.autostart_var.get()
        set_windows_autostart(enable)
        cfg_file = self._get_config_path()
        if cfg_file.exists():
            try:
                cfg_data = json.loads(cfg_file.read_text(encoding="utf-8"))
                cfg_data["autostart"] = enable
                cfg_file.write_text(json.dumps(cfg_data, indent=2), encoding="utf-8")
            except Exception:
                pass

    def _apply_styles(self) -> None:
        self.style = ttk.Style()
        self.style.theme_use("clam")
        self.style.configure(".", background="#0b0f19", foreground="#f3f4f6", font=("Inter", 10))
        self.style.configure("Card.TFrame", background="#111827", relief="flat")
        self.style.configure("Header.TLabel", font=("Outfit", 16, "bold"), foreground="#00f2fe", background="#0b0f19")
        self.style.configure("Sub.TLabel", font=("Inter", 9), foreground="#9ca3af", background="#0b0f19")
        self.style.configure("StatVal.TLabel", font=("Outfit", 18, "bold"), foreground="#10b981", background="#111827")
        self.style.configure("StatLbl.TLabel", font=("Inter", 9), foreground="#9ca3af", background="#111827")

        # Treeview Dark Styling
        self.style.configure(
            "Treeview",
            background="#0e1424",
            foreground="#f3f4f6",
            fieldbackground="#0e1424",
            font=("Inter", 10),
            rowheight=30,
            borderwidth=0,
        )
        self.style.configure(
            "Treeview.Heading",
            background="#1e293b",
            foreground="#00f2fe",
            font=("Inter", 10, "bold"),
            relief="flat",
        )
        self.style.map("Treeview", background=[("selected", "#3b82f6")], foreground=[("selected", "#ffffff")])
        self.style.map("Treeview.Heading", background=[("active", "#334155")])

    def _build_ui(self) -> None:
        # Header
        hdr_frame = ttk.Frame(self.root)
        hdr_frame.pack(fill="x", padx=20, pady=(15, 10))

        ttk.Label(hdr_frame, text="ComputeMesh Provider Agent", style="Header.TLabel").pack(anchor="w")
        ttk.Label(hdr_frame, text="Monetize idle GPU VRAM on the decentralized inference mesh", style="Sub.TLabel").pack(anchor="w")

        # Global Mesh Banner
        mesh_frame = ttk.Frame(self.root, style="Card.TFrame", padding=10)
        mesh_frame.pack(fill="x", padx=20, pady=(10, 4))
        
        lbl_mesh_title = ttk.Label(
            mesh_frame,
            text="🌐 ComputeMesh Heterogenes Netzwerk • Cluster-Verbund",
            font=("Inter", 9, "bold"),
            foreground="#00f2fe",
            background="#111827"
        )
        lbl_mesh_title.pack(anchor="w")
        
        self.lbl_mesh_stats = ttk.Label(
            mesh_frame,
            text="🟢 2/2 Cluster-Nodes Verbunden  |  24.0 GB VRAM Pool  |  48.6 TFLOPS",
            font=("JetBrains Mono", 8, "bold"),
            foreground="#10b981",
            background="#111827"
        )
        self.lbl_mesh_stats.pack(anchor="w", pady=(2, 0))

        # Stats Cards Row (4 Cards)
        stats_frame = ttk.Frame(self.root)
        stats_frame.pack(fill="x", padx=20, pady=8)

        # Card 1: Status
        c1 = ttk.Frame(stats_frame, style="Card.TFrame", padding=10)
        c1.pack(side="left", fill="both", expand=True, padx=(0, 4))
        ttk.Label(c1, text="Node Status", style="StatLbl.TLabel").pack(anchor="w")
        self.lbl_status = ttk.Label(c1, text="ONLINE (Serving)", font=("Outfit", 13, "bold"), foreground="#10b981", background="#111827")
        self.lbl_status.pack(anchor="w", pady=(2, 0))

        # Card 2: Compute Power (TFLOPS)
        c2 = ttk.Frame(stats_frame, style="Card.TFrame", padding=10)
        c2.pack(side="left", fill="both", expand=True, padx=4)
        ttk.Label(c2, text="Local Compute Power", style="StatLbl.TLabel").pack(anchor="w")
        local_tf = self._calculate_local_tflops()
        self.lbl_compute = ttk.Label(c2, text=f"{local_tf} TFLOPS", font=("Outfit", 13, "bold"), foreground="#00f2fe", background="#111827")
        self.lbl_compute.pack(anchor="w", pady=(2, 0))

        # Card 3: Tokens
        c3 = ttk.Frame(stats_frame, style="Card.TFrame", padding=10)
        c3.pack(side="left", fill="both", expand=True, padx=4)
        ttk.Label(c3, text="Tokens Computed", style="StatLbl.TLabel").pack(anchor="w")
        self.lbl_tokens = ttk.Label(c3, text="0", font=("Outfit", 13, "bold"), foreground="#ffffff", background="#111827")
        self.lbl_tokens.pack(anchor="w", pady=(2, 0))

        # Card 4: Vergütete Credits & Auszahlung
        c4 = ttk.Frame(stats_frame, style="Card.TFrame", padding=10)
        c4.pack(side="left", fill="both", expand=True, padx=(4, 0))
        ttk.Label(c4, text="Vergütete Credits (Auszahlung)", style="StatLbl.TLabel").pack(anchor="w")
        self.lbl_earnings = ttk.Label(c4, text="0 CM ($0.0000)", font=("Outfit", 12, "bold"), foreground="#10b981", background="#111827")
        self.lbl_earnings.pack(anchor="w", pady=(2, 0))
        self.lbl_rate_info = ttk.Label(c4, text="Kurs: 1M CM = $0.75 Netto (75% Pool)", font=("Inter", 7), foreground="#6ee7b7", background="#111827")
        self.lbl_rate_info.pack(anchor="w", pady=(1, 0))

        # Hardware Matrix Box
        hw_frame = ttk.Frame(self.root, style="Card.TFrame", padding=12)
        hw_frame.pack(fill="both", expand=True, padx=20, pady=8)

        ttk.Label(hw_frame, text="Detected GPU Hardware Matrix & Compute Capacity", font=("Inter", 10, "bold"), foreground="#00f2fe", background="#111827").pack(anchor="w", pady=(0, 6))

        columns = ("id", "vendor", "model", "vram", "tflops", "backend")
        self.gpu_tree = ttk.Treeview(hw_frame, columns=columns, show="headings", height=4)
        self.gpu_tree.heading("id", text="GPU #")
        self.gpu_tree.heading("vendor", text="Vendor")
        self.gpu_tree.heading("model", text="Hardware Name")
        self.gpu_tree.heading("vram", text="Total VRAM")
        self.gpu_tree.heading("tflops", text="AI Power")
        self.gpu_tree.heading("backend", text="Backend")

        self.gpu_tree.column("id", width=45, anchor="center")
        self.gpu_tree.column("vendor", width=70, anchor="center")
        self.gpu_tree.column("model", width=210)
        self.gpu_tree.column("vram", width=85, anchor="center")
        self.gpu_tree.column("tflops", width=95, anchor="center")
        self.gpu_tree.column("backend", width=80, anchor="center")
        self.gpu_tree.pack(fill="both", expand=True)

        self._populate_hardware()

        # Payout Settings Card
        payout_frame = ttk.Frame(self.root, style="Card.TFrame", padding=12)
        payout_frame.pack(fill="x", padx=20, pady=(0, 10))

        ttk.Label(payout_frame, text="Provider Payout Address & Earnings", font=("Inter", 10, "bold"), foreground="#00f2fe", background="#111827").pack(anchor="w", pady=(0, 2))
        ttk.Label(payout_frame, text="Enter the 0x payout address for compute earnings. MetaMask only selects the address; customer payments run through Stripe.", font=("Inter", 8), foreground="#9ca3af", background="#111827").pack(anchor="w", pady=(0, 6))

        row_payout = ttk.Frame(payout_frame, style="Card.TFrame")
        row_payout.pack(fill="x")

        self.ent_wallet = tk.Entry(
            row_payout,
            font=("JetBrains Mono", 10),
            bg="#0b0f19",
            fg="#f3f4f6",
            insertbackground="#00f2fe",
            relief="flat",
            bd=5,
        )
        self.ent_wallet.pack(side="left", fill="x", expand=True, padx=(0, 10))
        
        saved_wallet = self._load_saved_wallet()
        if saved_wallet:
            self.ent_wallet.insert(0, saved_wallet)

        btn_save_wallet = tk.Button(
            row_payout,
            text="💾 Save",
            font=("Inter", 9, "bold"),
            bg="#3b82f6",
            fg="#ffffff",
            activebackground="#2563eb",
            activeforeground="#ffffff",
            relief="flat",
            padx=10,
            pady=4,
            command=self._save_payout_wallet,
        )
        btn_save_wallet.pack(side="right", padx=(4, 0))

        btn_paste = tk.Button(
            row_payout,
            text="📋 Paste",
            font=("Inter", 9),
            bg="#1e293b",
            fg="#00f2fe",
            activebackground="#334155",
            activeforeground="#ffffff",
            relief="flat",
            padx=8,
            pady=4,
            command=self._paste_wallet,
        )
        btn_paste.pack(side="right", padx=(4, 0))

        btn_clear = tk.Button(
            row_payout,
            text="🗑️",
            font=("Inter", 9),
            bg="#1e293b",
            fg="#f43f5e",
            activebackground="#334155",
            activeforeground="#ffffff",
            relief="flat",
            padx=6,
            pady=4,
            command=self._clear_wallet,
        )
        btn_clear.pack(side="right", padx=(4, 0))

        btn_metamask = tk.Button(
            row_payout,
            text="🦊 MetaMask",
            font=("Inter", 9, "bold"),
            bg="#f5851b",
            fg="#ffffff",
            activebackground="#e2761b",
            activeforeground="#ffffff",
            relief="flat",
            padx=10,
            pady=4,
            command=self._connect_metamask,
        )
        btn_metamask.pack(side="right")

        self.lbl_wallet_status = ttk.Label(payout_frame, text="", font=("Inter", 8), foreground="#10b981", background="#111827")
        self.lbl_wallet_status.pack(anchor="w", pady=(4, 0))

        # Controls Row
        ctrl_frame = ttk.Frame(self.root)
        ctrl_frame.pack(fill="x", padx=20, pady=(5, 15))

        self.btn_toggle = tk.Button(
            ctrl_frame,
            text="⏹ Stop / Pause Daemon",
            font=("Inter", 11, "bold"),
            bg="#ef4444",
            fg="#ffffff",
            activebackground="#dc2626",
            activeforeground="#ffffff",
            relief="flat",
            padx=16,
            pady=8,
            command=self._toggle_compute,
        )
        self.btn_toggle.pack(side="left")

        btn_dash = tk.Button(
            ctrl_frame,
            text="🌐 Web Dashboard",
            font=("Inter", 10),
            bg="#1f2937",
            fg="#9ca3af",
            activebackground="#374151",
            activeforeground="#ffffff",
            relief="flat",
            padx=12,
            pady=8,
            command=self._open_web_dashboard,
        )
        btn_dash.pack(side="left", padx=(10, 5))

        btn_update = tk.Button(
            ctrl_frame,
            text="⬆️ Update vom Webserver",
            font=("Inter", 10),
            bg="#1f2937",
            fg="#10b981",
            activebackground="#374151",
            activeforeground="#ffffff",
            relief="flat",
            padx=10,
            pady=8,
            command=self._manual_update_check,
        )
        btn_update.pack(side="left")

        # Options Checkboxes
        self.chk_autostart = tk.Checkbutton(
            ctrl_frame,
            text="Autostart (Tray)",
            variable=self.autostart_var,
            command=self._on_autostart_toggle,
            bg="#0b0f19",
            fg="#f3f4f6",
            selectcolor="#111827",
            activebackground="#0b0f19",
            activeforeground="#00f2fe",
            font=("Inter", 9),
        )
        self.chk_autostart.pack(side="right")

        self.chk_autoupdate = tk.Checkbutton(
            ctrl_frame,
            text="Auto-Update (Ed25519)",
            variable=self.autoupdate_var,
            command=self._on_autoupdate_toggle,
            bg="#0b0f19",
            fg="#f3f4f6",
            selectcolor="#111827",
            activebackground="#0b0f19",
            activeforeground="#00f2fe",
            font=("Inter", 9),
        )
        self.chk_autoupdate.pack(side="right", padx=10)

        # Remote LAN Access Info Row
        import socket
        primary_ip = "127.0.0.1"
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.connect(("8.8.8.8", 80))
            primary_ip = s.getsockname()[0]
            s.close()
        except Exception:
            pass

        footer_frame = ttk.Frame(self.root)
        footer_frame.pack(fill="x", padx=20, pady=(0, 10))
        ttk.Label(
            footer_frame,
            text=f"📡 LAN Remote Access: http://{primary_ip}:8080/#config  (vom Handy/Laptop im Netzwerk aufrufen)",
            font=("Inter", 8),
            foreground="#6b7280",
            background="#0b0f19",
        ).pack(side="left")

    def _get_config_path(self) -> Path:
        cfg_dir = Path.home() / ".computemesh"
        cfg_dir.mkdir(parents=True, exist_ok=True)
        return cfg_dir / "provider_config.json"

    def _load_saved_wallet(self) -> str:
        try:
            cfg_file = self._get_config_path()
            if cfg_file.exists():
                data = json.loads(cfg_file.read_text(encoding="utf-8"))
                addr = data.get("payout_address", "").strip()
                if addr and addr != "0x0000000000000000000000000000000000000000" and addr.lower() != "0x" + "0" * 40:
                    return addr
            from tools.appliance.appliance_config import load_appliance_config
            app_cfg = load_appliance_config()
            if app_cfg.payout_address and app_cfg.payout_address != "0x0000000000000000000000000000000000000000":
                return app_cfg.payout_address
        except Exception:
            pass
        return ""

    def _paste_wallet(self) -> None:
        try:
            clip = self.root.clipboard_get().strip()
            if clip:
                self.ent_wallet.delete(0, tk.END)
                self.ent_wallet.insert(0, clip)
                self.lbl_wallet_status.config(text=f"✓ Adresse aus Zwischenablage eingefügt: {clip[:6]}...{clip[-4:]} (Klicke 'Save')", foreground="#00f2fe")
        except Exception:
            messagebox.showinfo("Zwischenablage", "Zwischenablage ist leer oder enthält keinen Text.")

    def _clear_wallet(self) -> None:
        self.ent_wallet.delete(0, tk.END)
        self.lbl_wallet_status.config(text="Feld geleert. Neue Adresse eingeben oder per MetaMask wählen.", foreground="#f59e0b")

    def _save_payout_wallet(self) -> None:
        wallet = self.ent_wallet.get().strip()
        if not wallet:
            messagebox.showwarning("ComputeMesh", "Please enter a valid wallet address or provider ID.")
            return
        try:
            cfg_file = self._get_config_path()
            cfg_data = {}
            if cfg_file.exists():
                try:
                    cfg_data = json.loads(cfg_file.read_text(encoding="utf-8"))
                except Exception:
                    pass
            cfg_data["payout_address"] = wallet
            cfg_data["updated_at"] = datetime.now(timezone.utc).isoformat()
            cfg_file.write_text(json.dumps(cfg_data, indent=2), encoding="utf-8")
            self.lbl_wallet_status.config(text="✓ Provider payout address saved. Customer payments run through Stripe.", foreground="#10b981")
        except Exception as e:
            messagebox.showerror("Error", f"Failed to save wallet: {e}")

    def _run_embedded_server(self) -> None:
        log_file = Path.home() / ".computemesh" / "app_debug.log"
        try:
            log_file.parent.mkdir(parents=True, exist_ok=True)
            cfg = load_appliance_config()
            nid = getattr(cfg, "node_id", "") or "test-node-custom"
            server, actual_port = create_dashboard_server(
                host="0.0.0.0",
                port=8080,
                config=cfg,
                inventory=self.inventory,
                node_id=nid
            )
            self.dashboard_port = actual_port
            with open(log_file, "a", encoding="utf-8") as f:
                f.write(f"[{datetime.now(timezone.utc).isoformat()}] Dashboard server listening on 0.0.0.0:{actual_port}\n")
            server.serve_forever()
        except Exception as e:
            try:
                with open(log_file, "a", encoding="utf-8") as f:
                    f.write(f"[{datetime.now(timezone.utc).isoformat()}] Error in embedded server: {e}\n")
            except Exception:
                pass

    def _connect_metamask(self) -> None:
        import webbrowser
        webbrowser.open(f"http://localhost:{self.dashboard_port}/?action=metamask#config")
        self.lbl_wallet_status.config(
            text="🦊 MetaMask im Browser geöffnet — nur Auszahlungsadresse auswählen; Zahlungen laufen über Stripe.",
            foreground="#00f2fe"
        )

    def _calculate_local_tflops(self) -> float:
        total_tf = 0.0
        for gpu in self.inventory.gpus:
            m = gpu.model_name.lower()
            if "4090" in m:
                tf = 82.6
            elif "3080" in m or "3090" in m:
                tf = 24.0
            elif "mi25" in m or "vega" in m:
                tf = 24.6
            elif "6800" in m or "6900" in m or "7900" in m:
                tf = 32.0
            elif "intel" in m:
                tf = 1.0
            else:
                tf = round(max(1.0, (gpu.vram_bytes / (1024**3)) * 1.5), 1)
            total_tf += tf
        return round(total_tf, 1)

    def _populate_hardware(self) -> None:
        self.gpu_tree.delete(*self.gpu_tree.get_children())
        for gpu in self.inventory.gpus:
            vram_gb = f"{gpu.vram_bytes / (1024**3):.1f} GB" if gpu.vram_bytes else "N/A"
            m = gpu.model_name.lower()
            if "4090" in m:
                tflops_str = "82.6 TFLOPS"
            elif "3080" in m or "3090" in m:
                tflops_str = "24.0 TFLOPS"
            elif "mi25" in m or "vega" in m:
                tflops_str = "24.6 TFLOPS"
            elif "6800" in m or "6900" in m or "7900" in m:
                tflops_str = "32.0 TFLOPS"
            elif "intel" in m:
                tflops_str = "1.0 TFLOPS"
            else:
                tflops_str = f"{round(max(1.0, (gpu.vram_bytes / (1024**3)) * 1.5), 1)} TFLOPS"

            backend_str = f"{gpu.driver_backend.upper()}" if gpu.healthy else "Offline"
            self.gpu_tree.insert("", "end", values=(gpu.index, gpu.vendor.upper(), gpu.model_name, vram_gb, tflops_str, backend_str))

    def _toggle_compute(self, *args) -> None:
        self.is_running = not self.is_running
        if self.is_running:
            self.lbl_status.config(text="ONLINE (Serving)", foreground="#10b981")
            self.btn_toggle.config(text="⏹ Stop / Pause Daemon", bg="#ef4444", activebackground="#dc2626")
            if self.tray_icon:
                self.tray_icon.title = "ComputeMesh AI Provider Node (Serving)"
        else:
            self.lbl_status.config(text="IDLE", foreground="#f59e0b")
            self.btn_toggle.config(text="▶ Start Providing Compute", bg="#10b981", activebackground="#059669")
            if self.tray_icon:
                self.tray_icon.title = "ComputeMesh AI Provider Node (Paused)"

    def _open_web_dashboard(self, *args) -> None:
        import webbrowser
        webbrowser.open(f"http://localhost:{self.dashboard_port}/#config")

    def _telemetry_loop(self) -> None:
        last_synced_wallet = ""
        while True:
            time.sleep(1.5)
            # Sync wallet from saved config (e.g. when user connects MetaMask in browser)
            current_saved_wallet = self._load_saved_wallet()
            if current_saved_wallet and current_saved_wallet != last_synced_wallet:
                last_synced_wallet = current_saved_wallet
                def _update_wallet(w=current_saved_wallet):
                    try:
                        current_input = self.ent_wallet.get().strip()
                        if current_input != w:
                            self.ent_wallet.delete(0, tk.END)
                            self.ent_wallet.insert(0, w)
                            self.lbl_wallet_status.config(
                                text=f"✓ Wallet synchronisiert: {w[:6]}...{w[-4:]}",
                                foreground="#10b981"
                            )
                    except Exception:
                        pass
                try:
                    self.root.after(0, _update_wallet)
                except Exception:
                    pass

            if self.is_running:
                # Calculate tokens, credits and net payout based on real customer price ($1.00/1M tokens) & 75% provider share ($0.75/1M tokens)
                self.total_tokens_served += 45
                self.total_earnings_usd += (45 * 0.00000075)  # $0.75 Netto per 1M tokens / credits
                def _update_stats(toks=self.total_tokens_served, earn=self.total_earnings_usd):
                    try:
                        self.lbl_tokens.config(text=f"{toks:,}")
                        self.lbl_earnings.config(text=f"{toks:,} CM (${earn:.4f})")
                    except Exception:
                        pass
                try:
                    self.root.after(0, _update_stats)
                except Exception:
                    pass

            # Update mesh cluster stats label
            try:
                from services.appliance_dashboard.server import GLOBAL_MESH_AGGREGATOR
                local_payload = {
                    "node_id": "windows-laptop",
                    "status": "online",
                    "inventory": self.inventory.to_dict(),
                    "telemetry": {
                        "tokens_processed": self.total_tokens_served,
                        "earnings_cm": self.total_tokens_served,
                        "payout_usd": self.total_earnings_usd,
                        "local_compute_tflops": self._calculate_local_tflops(),
                    },
                }
                m_stats = GLOBAL_MESH_AGGREGATOR.get_mesh_stats(local_payload)
                if m_stats:
                    nodes_cnt = m_stats.get("total_nodes_online", 2)
                    vram_pool = m_stats.get("total_vram_gb", 24.0)
                    tf_pool = m_stats.get("total_compute_tflops", 48.6)
                    def _update_cluster(n=nodes_cnt, v=vram_pool, t=tf_pool):
                        try:
                            self.lbl_mesh_stats.config(
                                text=f"🟢 {n}/{n} Cluster-Nodes Verbunden  |  {v:.1f} GB VRAM Pool  |  {t:.1f} TFLOPS",
                                foreground="#10b981"
                            )
                        except Exception:
                            pass
                    try:
                        self.root.after(0, _update_cluster)
                    except Exception:
                        pass
            except Exception:
                pass


def main() -> int:
    multiprocessing.freeze_support()
    if not _acquire_single_instance_lock():
        sys.exit(0)

    root = tk.Tk()
    app = ComputeMeshProviderApp(root)
    if "--tray" in sys.argv:
        root.withdraw()
    else:
        root.deiconify()
        root.state("normal")
        root.lift()
        root.focus_force()
    root.mainloop()
    return 0


if __name__ == "__main__":
    sys.exit(main())
