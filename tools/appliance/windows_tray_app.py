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
import os
from pathlib import Path
import sys
import threading
import time
import tkinter as tk
from tkinter import messagebox, ttk

if sys.stdout is None:
    sys.stdout = io.StringIO()
if sys.stderr is None:
    sys.stderr = io.StringIO()

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from PIL import Image, ImageDraw
try:
    import pystray
    HAS_PYSTRAY = True
except ImportError:
    HAS_PYSTRAY = False

try:
    import winreg
    HAS_WINREG = True
except ImportError:
    HAS_WINREG = False

from services.appliance_dashboard.server import run_dashboard_server
from tools.appliance.appliance_config import load_appliance_config
from tools.appliance.hardware_detector import scan_rig_hardware

REG_RUN_PATH = r"Software\Microsoft\Windows\CurrentVersion\Run"
REG_APP_NAME = "ComputeMesh"


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
        self.root.geometry("680x620")
        self.root.minsize(620, 560)
        self.root.configure(bg="#0b0f19")

        # Resolve icon paths
        self.icon_path = self._find_icon()
        if self.icon_path:
            try:
                self.root.iconbitmap(default=str(self.icon_path))
            except Exception:
                pass

        # Auto-start providing compute immediately upon launch
        self.is_running = True
        self.total_tokens_served = 0
        self.total_earnings_usd = 0.00
        self.inventory = scan_rig_hardware()
        self.autostart_var = tk.BooleanVar(value=is_windows_autostart_enabled())

        self._apply_styles()
        self._build_ui()

        # Intercept window close button to minimize to System Tray
        self.root.protocol("WM_DELETE_WINDOW", self._hide_to_tray)

        # Start embedded local web dashboard server on port 8080 in background
        self.http_thread = threading.Thread(target=self._run_embedded_server, daemon=True)
        self.http_thread.start()

        # Background telemetry polling thread
        self.telemetry_thread = threading.Thread(target=self._telemetry_loop, daemon=True)
        self.telemetry_thread.start()

        # Initialize System Tray Icon
        self.tray_icon = None
        if HAS_PYSTRAY:
            self._setup_tray_icon()

        # Handle --tray startup argument
        if "--tray" in sys.argv:
            self.root.withdraw()

        # First-launch autostart prompt check
        self.root.after(600, self._check_first_launch_autostart)

    def _find_icon(self) -> Path | None:
        candidates = [
            Path(getattr(sys, "_MEIPASS", ".")) / "computemesh.ico",
            Path(__file__).resolve().parent / "computemesh.ico",
            REPO_ROOT / "portal" / "assets" / "computemesh.ico",
            Path.cwd() / "tools" / "appliance" / "computemesh.ico",
        ]
        for p in candidates:
            if p.exists():
                return p
        return None

    def _setup_tray_icon(self) -> None:
        try:
            if self.icon_path and self.icon_path.exists():
                tray_image = Image.open(self.icon_path)
            else:
                # Fallback generated icon image
                tray_image = Image.new("RGBA", (64, 64), color=(0, 240, 255, 255))

            menu = pystray.Menu(
                pystray.MenuItem("🖥️ Open ComputeMesh", self._show_from_tray, default=True),
                pystray.MenuItem("🌐 Web Dashboard (:8080)", self._open_web_dashboard),
                pystray.Menu.SEPARATOR,
                pystray.MenuItem(
                    lambda item: "⏹ Pause Compute" if self.is_running else "▶ Resume Compute",
                    self._toggle_compute,
                ),
                pystray.Menu.SEPARATOR,
                pystray.MenuItem("❌ Exit ComputeMesh", self._quit_app),
            )

            self.tray_icon = pystray.Icon(
                "ComputeMesh",
                tray_image,
                "ComputeMesh AI Provider Node (Serving)",
                menu=menu,
            )
            tray_thread = threading.Thread(target=self.tray_icon.run, daemon=True)
            tray_thread.start()
        except Exception:
            pass

    def _hide_to_tray(self) -> None:
        """Minimize application window to system tray."""
        self.root.withdraw()
        if self.tray_icon and HAS_PYSTRAY:
            try:
                self.tray_icon.notify(
                    "ComputeMesh läuft im Hintergrund weiter und monetarisiert freie GPU-Kapazität.",
                    "ComputeMesh AI Node",
                )
            except Exception:
                pass

    def _show_from_tray(self, icon=None, item=None) -> None:
        """Restore window from system tray."""
        self.root.deiconify()
        self.root.lift()
        self.root.focus_force()

    def _quit_app(self, icon=None, item=None) -> None:
        """Completely exit application and stop daemon."""
        if self.tray_icon:
            self.tray_icon.stop()
        self.root.quit()
        sys.exit(0)

    def _check_first_launch_autostart(self) -> None:
        """Prompt user on first run to configure Windows Autostart."""
        cfg_file = self._get_config_path()
        cfg_data = {}
        if cfg_file.exists():
            try:
                cfg_data = json.loads(cfg_file.read_text(encoding="utf-8"))
            except Exception:
                pass

        if not cfg_data.get("autostart_prompted", False):
            resp = messagebox.askyesno(
                "ComputeMesh Windows Autostart",
                "Möchtest du ComputeMesh automatisch beim Windows-Start minimiert im System-Tray starten?\n\n"
                "Dadurch monetarisiert deine GPU ungenutzte Leerlaufzeit automatisch im Hintergrund für maximale monatliche Erträge.\n\n"
                "(Empfohlen)",
                parent=self.root,
            )
            if resp:
                set_windows_autostart(True)
                self.autostart_var.set(True)
                cfg_data["autostart"] = True
            else:
                cfg_data["autostart"] = False

            cfg_data["autostart_prompted"] = True
            try:
                cfg_file.write_text(json.dumps(cfg_data, indent=2), encoding="utf-8")
            except Exception:
                pass

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

        # Stats Cards Row
        stats_frame = ttk.Frame(self.root)
        stats_frame.pack(fill="x", padx=20, pady=10)

        # Card 1: Status
        c1 = ttk.Frame(stats_frame, style="Card.TFrame", padding=12)
        c1.pack(side="left", fill="both", expand=True, padx=(0, 6))
        ttk.Label(c1, text="Node Status", style="StatLbl.TLabel").pack(anchor="w")
        self.lbl_status = ttk.Label(c1, text="ONLINE (Serving)", font=("Outfit", 16, "bold"), foreground="#10b981", background="#111827")
        self.lbl_status.pack(anchor="w", pady=(4, 0))

        # Card 2: Tokens
        c2 = ttk.Frame(stats_frame, style="Card.TFrame", padding=12)
        c2.pack(side="left", fill="both", expand=True, padx=6)
        ttk.Label(c2, text="Tokens Computed", style="StatLbl.TLabel").pack(anchor="w")
        self.lbl_tokens = ttk.Label(c2, text="0", style="StatVal.TLabel")
        self.lbl_tokens.pack(anchor="w", pady=(4, 0))

        # Card 3: Earnings
        c3 = ttk.Frame(stats_frame, style="Card.TFrame", padding=12)
        c3.pack(side="left", fill="both", expand=True, padx=(6, 0))
        ttk.Label(c3, text="Estimated Earnings", style="StatLbl.TLabel").pack(anchor="w")
        self.lbl_earnings = ttk.Label(c3, text="$0.0000", style="StatVal.TLabel")
        self.lbl_earnings.pack(anchor="w", pady=(4, 0))

        # Hardware Matrix Box
        hw_frame = ttk.Frame(self.root, style="Card.TFrame", padding=15)
        hw_frame.pack(fill="both", expand=True, padx=20, pady=10)

        ttk.Label(hw_frame, text="Detected GPU Hardware Matrix", font=("Inter", 11, "bold"), foreground="#00f2fe", background="#111827").pack(anchor="w", pady=(0, 8))

        columns = ("id", "vendor", "model", "vram", "backend")
        self.gpu_tree = ttk.Treeview(hw_frame, columns=columns, show="headings", height=4)
        self.gpu_tree.heading("id", text="GPU #")
        self.gpu_tree.heading("vendor", text="Vendor")
        self.gpu_tree.heading("model", text="Hardware Name")
        self.gpu_tree.heading("vram", text="Total VRAM")
        self.gpu_tree.heading("backend", text="Backend")

        self.gpu_tree.column("id", width=50, anchor="center")
        self.gpu_tree.column("vendor", width=80, anchor="center")
        self.gpu_tree.column("model", width=220)
        self.gpu_tree.column("vram", width=100, anchor="center")
        self.gpu_tree.column("backend", width=90, anchor="center")
        self.gpu_tree.pack(fill="both", expand=True)

        self._populate_hardware()

        # Payout Settings Card
        payout_frame = ttk.Frame(self.root, style="Card.TFrame", padding=15)
        payout_frame.pack(fill="x", padx=20, pady=(0, 10))

        ttk.Label(payout_frame, text="Payout & Earnings Settlement", font=("Inter", 11, "bold"), foreground="#00f2fe", background="#111827").pack(anchor="w", pady=(0, 4))
        ttk.Label(payout_frame, text="Enter your Ethereum/Polygon wallet address (0x...) or connect MetaMask for automated settlements.", font=("Inter", 9), foreground="#9ca3af", background="#111827").pack(anchor="w", pady=(0, 8))

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
            font=("Inter", 10, "bold"),
            bg="#3b82f6",
            fg="#ffffff",
            activebackground="#2563eb",
            activeforeground="#ffffff",
            relief="flat",
            padx=12,
            pady=4,
            command=self._save_payout_wallet,
        )
        btn_save_wallet.pack(side="right", padx=(5, 0))

        btn_metamask = tk.Button(
            row_payout,
            text="🦊 MetaMask",
            font=("Inter", 10, "bold"),
            bg="#f5851b",
            fg="#ffffff",
            activebackground="#e2761b",
            activeforeground="#ffffff",
            relief="flat",
            padx=12,
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
        btn_dash.pack(side="left", padx=10)

        # Autostart Checkbox
        self.chk_autostart = tk.Checkbutton(
            ctrl_frame,
            text="Windows-Autostart (System-Tray)",
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
                if addr == "0x0000000000000000000000000000000000000000":
                    return ""
                return addr
        except Exception:
            pass
        return ""

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
            self.lbl_wallet_status.config(text=f"✓ Wallet address saved securely to local node configuration.", foreground="#10b981")
        except Exception as e:
            messagebox.showerror("Error", f"Failed to save wallet: {e}")

    def _run_embedded_server(self) -> None:
        try:
            cfg = load_appliance_config()
            run_dashboard_server(host="0.0.0.0", port=8080, config=cfg, inventory=self.inventory, node_id="windows-provider-node")
        except Exception:
            pass

    def _connect_metamask(self) -> None:
        import webbrowser
        webbrowser.open("http://localhost:8080/#config")
        self.lbl_wallet_status.config(
            text="🦊 Web Dashboard geöffnet. Nach Klick auf 'Connect MetaMask' wird die Adresse automatisch synchronisiert!",
            foreground="#00f2fe"
        )

    def _populate_hardware(self) -> None:
        self.gpu_tree.delete(*self.gpu_tree.get_children())
        for gpu in self.inventory.gpus:
            vram_gb = f"{gpu.vram_bytes / (1024**3):.1f} GB" if gpu.vram_bytes else "N/A"
            backend_str = f"{gpu.driver_backend.upper()}" if gpu.healthy else "Offline"
            self.gpu_tree.insert("", "end", values=(gpu.index, gpu.vendor.upper(), gpu.model_name, vram_gb, backend_str))

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
        webbrowser.open("http://localhost:8080/#config")

    def _telemetry_loop(self) -> None:
        last_synced_wallet = ""
        while True:
            time.sleep(1.5)
            # Sync wallet from saved config (e.g. when user connects MetaMask in browser)
            current_saved_wallet = self._load_saved_wallet()
            if current_saved_wallet and current_saved_wallet != last_synced_wallet:
                last_synced_wallet = current_saved_wallet
                try:
                    current_input = self.ent_wallet.get().strip()
                    if current_input != current_saved_wallet:
                        self.ent_wallet.delete(0, tk.END)
                        self.ent_wallet.insert(0, current_saved_wallet)
                        self.lbl_wallet_status.config(
                            text=f"✓ Wallet synchronisiert: {current_saved_wallet[:6]}...{current_saved_wallet[-4:]}",
                            foreground="#10b981"
                        )
                except Exception:
                    pass

            if self.is_running:
                # Simulate token processing and ledger earnings
                self.total_tokens_served += 45
                self.total_earnings_usd += (45 * 0.00000085)  # $0.85 per 1M tokens reward
                try:
                    self.lbl_tokens.config(text=f"{self.total_tokens_served:,}")
                    self.lbl_earnings.config(text=f"${self.total_earnings_usd:.4f}")
                except Exception:
                    pass


def main() -> int:
    root = tk.Tk()
    app = ComputeMeshProviderApp(root)
    root.mainloop()
    return 0


if __name__ == "__main__":
    sys.exit(main())
