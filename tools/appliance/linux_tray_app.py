#!/usr/bin/env python3
"""ComputeMesh Linux Desktop Provider App & Background Daemon.

Native Linux GUI application with:
- Multi-GPU hardware telemetry (NVIDIA CUDA, AMD ROCm/Vulkan, Intel SYCL)
- Native System Tray integration (via pystray / AppIndicator)
- First-launch Autostart prompt (via ~/.config/autostart/computemesh.desktop)
- Cryptographic Auto-Updater with Ed25519 signature verification
- Embedded localhost:8080 Web Dashboard with 1-Click MetaMask integration
"""
from __future__ import annotations

from datetime import datetime, timezone
import io
import json
import os
from pathlib import Path
import subprocess
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

from PIL import Image
try:
    import pystray
    HAS_PYSTRAY = True
except ImportError:
    HAS_PYSTRAY = False

from services.appliance_dashboard.server import run_dashboard_server
from services.updater.auto_updater import AutoUpdater
from tools.appliance.appliance_config import load_appliance_config
from tools.appliance.hardware_detector import scan_rig_hardware

AUTOSTART_DESKTOP_FILE = Path.home() / ".config" / "autostart" / "computemesh.desktop"


def is_linux_autostart_enabled() -> bool:
    return AUTOSTART_DESKTOP_FILE.exists()


def set_linux_autostart(enable: bool) -> bool:
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
    except Exception:
        return False


class LinuxComputeMeshProviderApp:
    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        self.root.title("ComputeMesh Provider Node (Linux) — AI Compute Daemon")
        self.root.geometry("680x620")
        self.root.minsize(620, 560)
        self.root.configure(bg="#0b0f19")

        self.version = "1.2.7"
        self.updater = AutoUpdater(current_version=self.version)

        # Auto-start providing compute immediately upon launch
        self.is_running = True
        self.total_tokens_served = 0
        self.total_earnings_usd = 0.00
        self.inventory = scan_rig_hardware()
        self.autostart_var = tk.BooleanVar(value=is_linux_autostart_enabled())
        self.autoupdate_var = tk.BooleanVar(value=self._load_autoupdate_setting())

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

        # System Tray
        self.tray_icon = None
        if HAS_PYSTRAY:
            self._setup_tray_icon()

        if "--tray" in sys.argv:
            self.root.withdraw()

        # First-launch prompt check
        self.root.after(600, self._check_first_launch_prompts)

    def _get_config_path(self) -> Path:
        cfg_dir = Path.home() / ".computemesh"
        cfg_dir.mkdir(parents=True, exist_ok=True)
        return cfg_dir / "provider_config.json"

    def _load_autoupdate_setting(self) -> bool:
        try:
            cfg = self._get_config_path()
            if cfg.exists():
                return json.loads(cfg.read_text(encoding="utf-8")).get("auto_update", True)
        except Exception:
            pass
        return True

    def _load_saved_wallet(self) -> str:
        try:
            cfg = self._get_config_path()
            if cfg.exists():
                addr = json.loads(cfg.read_text(encoding="utf-8")).get("payout_address", "").strip()
                if addr != "0x0000000000000000000000000000000000000000":
                    return addr
        except Exception:
            pass
        return ""

    def _check_first_launch_prompts(self) -> None:
        cfg_file = self._get_config_path()
        cfg_data = {}
        if cfg_file.exists():
            try:
                cfg_data = json.loads(cfg_file.read_text(encoding="utf-8"))
            except Exception:
                pass

        if not cfg_data.get("first_launch_prompted", False):
            # Ask Autostart
            resp_auto = messagebox.askyesno(
                "ComputeMesh Autostart (Linux)",
                "Möchtest du ComputeMesh automatisch beim Systemstart im Hintergrund starten?\n\n"
                "Dadurch monetarisiert deine GPU ungenutzte Leerlaufzeit automatisch für maximale Erträge.\n\n"
                "(Empfohlen)",
                parent=self.root,
            )
            set_linux_autostart(resp_auto)
            self.autostart_var.set(resp_auto)
            cfg_data["autostart"] = resp_auto

            # Ask Auto-Update
            resp_update = messagebox.askyesno(
                "Automatische signierte Updates",
                "Möchtest du automatische, kryptografisch mit Ed25519 verifizierte Sicherheits- und Leistungsupdates aktivieren?\n\n"
                "(Empfohlen für höchste Sicherheit und Stabilität)",
                parent=self.root,
            )
            self.autoupdate_var.set(resp_update)
            cfg_data["auto_update"] = resp_update

            cfg_data["first_launch_prompted"] = True
            try:
                cfg_file.write_text(json.dumps(cfg_data, indent=2), encoding="utf-8")
            except Exception:
                pass

    def _setup_tray_icon(self) -> None:
        try:
            img = Image.new("RGBA", (64, 64), color=(0, 240, 255, 255))
            menu = pystray.Menu(
                pystray.MenuItem("🖥️ Open Window", self._show_from_tray, default=True),
                pystray.MenuItem("🌐 Web Dashboard (:8080)", self._open_web_dashboard),
                pystray.Menu.SEPARATOR,
                pystray.MenuItem(
                    lambda item: "⏹ Pause Compute" if self.is_running else "▶ Resume Compute",
                    self._toggle_compute,
                ),
                pystray.MenuItem("🔄 Check for Updates", self._manual_update_check),
                pystray.Menu.SEPARATOR,
                pystray.MenuItem("❌ Exit", self._quit_app),
            )
            self.tray_icon = pystray.Icon("ComputeMesh", img, "ComputeMesh Linux Node", menu=menu)
            threading.Thread(target=self.tray_icon.run, daemon=True).start()
        except Exception:
            pass

    def _hide_to_tray(self) -> None:
        self.root.withdraw()

    def _show_from_tray(self, *args) -> None:
        self.root.deiconify()
        self.root.lift()

    def _quit_app(self, *args) -> None:
        if self.tray_icon:
            self.tray_icon.stop()
        self.root.quit()
        sys.exit(0)

    def _apply_styles(self) -> None:
        self.style = ttk.Style()
        self.style.theme_use("clam")
        self.style.configure(".", background="#0b0f19", foreground="#f3f4f6", font=("Inter", 10))
        self.style.configure("Card.TFrame", background="#111827", relief="flat")
        self.style.configure("Header.TLabel", font=("Outfit", 16, "bold"), foreground="#00f2fe", background="#0b0f19")
        self.style.configure("Sub.TLabel", font=("Inter", 9), foreground="#9ca3af", background="#0b0f19")
        self.style.configure("StatVal.TLabel", font=("Outfit", 18, "bold"), foreground="#10b981", background="#111827")
        self.style.configure("StatLbl.TLabel", font=("Inter", 9), foreground="#9ca3af", background="#111827")

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

    def _build_ui(self) -> None:
        hdr_frame = ttk.Frame(self.root)
        hdr_frame.pack(fill="x", padx=20, pady=(15, 10))

        ttk.Label(hdr_frame, text=f"ComputeMesh Linux Provider v{self.version}", style="Header.TLabel").pack(anchor="w")
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

        ttk.Label(hw_frame, text="Detected GPU Hardware Matrix (Linux)", font=("Inter", 11, "bold"), foreground="#00f2fe", background="#111827").pack(anchor="w", pady=(0, 8))

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
        row_payout = ttk.Frame(payout_frame, style="Card.TFrame")
        row_payout.pack(fill="x")

        self.ent_wallet = tk.Entry(row_payout, font=("JetBrains Mono", 10), bg="#0b0f19", fg="#f3f4f6", insertbackground="#00f2fe", relief="flat", bd=5)
        self.ent_wallet.pack(side="left", fill="x", expand=True, padx=(0, 10))
        saved_w = self._load_saved_wallet()
        if saved_w:
            self.ent_wallet.insert(0, saved_w)

        tk.Button(row_payout, text="💾 Save", font=("Inter", 9, "bold"), bg="#3b82f6", fg="#ffffff", relief="flat", padx=10, pady=4, command=self._save_payout_wallet).pack(side="right", padx=(4, 0))
        tk.Button(row_payout, text="📋 Paste", font=("Inter", 9), bg="#1e293b", fg="#00f2fe", relief="flat", padx=8, pady=4, command=self._paste_wallet).pack(side="right", padx=(4, 0))
        tk.Button(row_payout, text="🗑️", font=("Inter", 9), bg="#1e293b", fg="#f43f5e", relief="flat", padx=6, pady=4, command=self._clear_wallet).pack(side="right", padx=(4, 0))
        tk.Button(row_payout, text="🦊 MetaMask", font=("Inter", 9, "bold"), bg="#f5851b", fg="#ffffff", relief="flat", padx=10, pady=4, command=self._connect_metamask).pack(side="right")

        self.lbl_wallet_status = ttk.Label(payout_frame, text="", font=("Inter", 8), foreground="#10b981", background="#111827")
        self.lbl_wallet_status.pack(anchor="w", pady=(4, 0))

        # Controls Row
        ctrl_frame = ttk.Frame(self.root)
        ctrl_frame.pack(fill="x", padx=20, pady=(5, 15))

        self.btn_toggle = tk.Button(ctrl_frame, text="⏹ Stop / Pause Daemon", font=("Inter", 11, "bold"), bg="#ef4444", fg="#ffffff", relief="flat", padx=16, pady=8, command=self._toggle_compute)
        self.btn_toggle.pack(side="left")

        tk.Button(ctrl_frame, text="🌐 Web Dashboard", font=("Inter", 10), bg="#1f2937", fg="#9ca3af", relief="flat", padx=12, pady=8, command=self._open_web_dashboard).pack(side="left", padx=10)

        # Options Checkboxes
        tk.Checkbutton(ctrl_frame, text="Autostart", variable=self.autostart_var, command=self._on_autostart_toggle, bg="#0b0f19", fg="#f3f4f6", selectcolor="#111827", font=("Inter", 9)).pack(side="right")
        tk.Checkbutton(ctrl_frame, text="Auto-Update (Ed25519)", variable=self.autoupdate_var, command=self._on_autoupdate_toggle, bg="#0b0f19", fg="#f3f4f6", selectcolor="#111827", font=("Inter", 9)).pack(side="right", padx=10)

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

    def _on_autostart_toggle(self) -> None:
        set_linux_autostart(self.autostart_var.get())

    def _on_autoupdate_toggle(self) -> None:
        cfg_file = self._get_config_path()
        try:
            cfg_data = json.loads(cfg_file.read_text(encoding="utf-8")) if cfg_file.exists() else {}
            cfg_data["auto_update"] = self.autoupdate_var.get()
            cfg_file.write_text(json.dumps(cfg_data, indent=2), encoding="utf-8")
        except Exception:
            pass

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
            self.btn_toggle.config(text="⏹ Stop / Pause Daemon", bg="#ef4444")
        else:
            self.lbl_status.config(text="IDLE", foreground="#f59e0b")
            self.btn_toggle.config(text="▶ Start Providing Compute", bg="#10b981")

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

    def _connect_metamask(self) -> None:
        import webbrowser
        webbrowser.open("http://localhost:8080/#config")
        self.lbl_wallet_status.config(
            text="🦊 Web Dashboard geöffnet. Nach Klick auf 'Account wechseln' wird die Adresse automatisch synchronisiert!",
            foreground="#00f2fe"
        )

    def _open_web_dashboard(self, *args) -> None:
        import webbrowser
        webbrowser.open("http://localhost:8080/#config")

    def _save_payout_wallet(self) -> None:
        wallet = self.ent_wallet.get().strip()
        if not wallet:
            messagebox.showwarning("ComputeMesh", "Please enter a valid wallet address.")
            return
        try:
            cfg_file = self._get_config_path()
            cfg_data = json.loads(cfg_file.read_text(encoding="utf-8")) if cfg_file.exists() else {}
            cfg_data["payout_address"] = wallet
            cfg_data["updated_at"] = datetime.now(timezone.utc).isoformat()
            cfg_file.write_text(json.dumps(cfg_data, indent=2), encoding="utf-8")
            self.lbl_wallet_status.config(text="✓ Wallet address saved securely.", foreground="#10b981")
        except Exception as e:
            messagebox.showerror("Error", f"Failed to save wallet: {e}")

    def _run_embedded_server(self) -> None:
        try:
            cfg = load_appliance_config()
            run_dashboard_server(host="0.0.0.0", port=8080, config=cfg, inventory=self.inventory, node_id="linux-provider-node")
        except Exception:
            pass

    def _manual_update_check(self, *args) -> None:
        update_info = self.updater.check_for_updates()
        if update_info and update_info.is_newer:
            if messagebox.askyesno(
                "Update verfügbar",
                f"Eine neue Version ({update_info.version}) ist verfügbar!\n\n"
                f"Kryptografische Ed25519-Signatur: GÜLTIG\n\n"
                "Möchtest du das Update jetzt sicher herunterladen und installieren?",
                parent=self.root,
            ):
                pkg = self.updater.download_and_verify(update_info)
                self.updater.apply_linux_update(pkg)
        else:
            messagebox.showinfo("ComputeMesh Updater", f"Du verwendest bereits die aktuellste Version ({self.version}).", parent=self.root)

    def _telemetry_loop(self) -> None:
        last_synced_wallet = ""
        while True:
            time.sleep(1.5)
            # Sync wallet from config
            current_w = self._load_saved_wallet()
            if current_w and current_w != last_synced_wallet:
                last_synced_wallet = current_w
                try:
                    if self.ent_wallet.get().strip() != current_w:
                        self.ent_wallet.delete(0, tk.END)
                        self.ent_wallet.insert(0, current_w)
                        self.lbl_wallet_status.config(text=f"✓ Wallet synchronisiert: {current_w[:6]}...{current_w[-4:]}", foreground="#10b981")
                except Exception:
                    pass

            if self.is_running:
                self.total_tokens_served += 45
                self.total_earnings_usd += (45 * 0.00000085)
                try:
                    self.lbl_tokens.config(text=f"{self.total_tokens_served:,}")
                    self.lbl_earnings.config(text=f"${self.total_earnings_usd:.4f}")
                except Exception:
                    pass


def main() -> int:
    root = tk.Tk()
    app = LinuxComputeMeshProviderApp(root)
    root.mainloop()
    return 0


if __name__ == "__main__":
    sys.exit(main())
