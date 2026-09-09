#!/usr/bin/env python3
"""ComputeMesh Windows Standalone Executable & Installer Packaging Engine.

Bundles the lightweight Windows Desktop Provider Agent GUI, hardware discovery modules,
and autostart registry templates into a self-contained installer executable.
"""
from __future__ import annotations

import hashlib
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]


def _pyinstaller_tcl_tk_options() -> list[str]:
    """Return explicit Tcl/Tk data options for one-file Windows builds.

    PyInstaller normally discovers these through its tkinter hook.  Keeping
    the data paths explicit is important for this app because tkinter is
    imported before the tray UI starts, and a missing Tcl/Tk tree causes an
    opaque ``_tkinter.TclError`` during application startup.
    """
    if sys.platform != "win32":
        return []

    tcl_root = Path(sys.base_prefix) / "tcl"
    tcl_dir = next((path for path in sorted(tcl_root.glob("tcl*"), reverse=True) if path.is_dir()), None)
    tk_dir = next((path for path in sorted(tcl_root.glob("tk*"), reverse=True) if path.is_dir()), None)
    if tcl_dir is None or tk_dir is None:
        raise RuntimeError(f"Python Tcl/Tk data directories not found below {tcl_root}")

    return [
        "--add-data",
        f"{tcl_dir};_tcl_data",
        "--add-data",
        f"{tk_dir};_tk_data",
        "--hidden-import",
        "_tkinter",
    ]



@dataclass(frozen=True)
class WindowsInstallerPackageResult:
    output_path: Path
    file_size_bytes: int
    sha256_hash: str
    manifest: dict[str, Any]


def build_windows_standalone_bundle(
    output_exe_path: Path,
    version: str = "1.0.0",
) -> WindowsInstallerPackageResult:
    """Builds a standalone executable installer bundle for Windows."""
    output_exe_path = Path(output_exe_path)
    output_exe_path.parent.mkdir(parents=True, exist_ok=True)

    # Create embedded manifest
    manifest = {
        "app_name": "ComputeMesh Provider Agent",
        "version": version,
        "platform": "windows-x64",
        "entrypoint": "__main__.py",
        "author": "ComputeMesh Network Foundation",
        "default_coordinator": "https://mesh.inetconnector.com",
    }
    # Build standalone executable with PyInstaller
    hidden_imports = [
        "config",
        "services",
        "services.common",
        "services.common.config",
        "services.appliance_dashboard",
        "services.appliance_dashboard.server",
        "services.appliance_dashboard.template_loader",
        "services.appliance_dashboard.network",
        "services.appliance_dashboard.mesh_aggregator",
        "services.appliance_dashboard.tunnel_relay",
        "services.updater",
        "services.updater.auto_updater",
        "services.billing",
        "services.billing.ledger",
        "tools",
        "tools.appliance",
        "tools.appliance.hardware_detector",
        "tools.appliance.appliance_config",
        "tools.appliance.token_metering",
        "tools.appliance.lan_discovery_responder",
        "tools.security",
        "tools.security.ed25519_verify",
        "tools.security.signing_keys",
        "PIL",
        "PIL.ImageTk",
        "PIL.ImageDraw",
        "PIL.IcoImagePlugin",
        "PIL.PngImagePlugin",
        "pystray",
        "pystray._win32",
        "pystray._util",
        "pystray._util.win32",
        "win32gui",
        "win32con",
        "win32api",
    ]
    hidden_import_args = []
    for h in hidden_imports:
        hidden_import_args.extend(["--hidden-import", h])

    cmd = [
        sys.executable, "-m", "PyInstaller",
        "--onefile",
        "--noconsole",
        "--name", output_exe_path.stem,
        "--distpath", str(output_exe_path.parent),
        "--workpath", str(output_exe_path.parent / "dist_build"),
        "--specpath", str(output_exe_path.parent / "dist_spec"),
        "--paths", str(REPO_ROOT),
        "--add-data", f"{REPO_ROOT / 'config.py'};.",
        "--add-data", f"{REPO_ROOT / 'services'};services",
        "--add-data", f"{REPO_ROOT / 'tools' / 'appliance'};tools/appliance",
        "--add-data", f"{REPO_ROOT / 'tools' / 'security'};tools/security",
        "--add-data", f"{REPO_ROOT / 'portal' / 'assets'};portal/assets",
        *_pyinstaller_tcl_tk_options(),
        *hidden_import_args,
        "--runtime-hook", str(REPO_ROOT / "deploy" / "windows" / "pyi_rth_tkinter.py"),
        str(REPO_ROOT / "tools" / "appliance" / "windows_tray_app.py"),
    ]

    try:
        import PyInstaller  # noqa: F401
    except ImportError as exc:
        raise RuntimeError("PyInstaller is required to build the Windows executable") from exc

    subprocess.run(cmd, check=True)
    if not output_exe_path.exists():
        raise RuntimeError(f"PyInstaller completed without creating {output_exe_path}")

    shutil.rmtree(output_exe_path.parent / "dist_build", ignore_errors=True)
    shutil.rmtree(output_exe_path.parent / "dist_spec", ignore_errors=True)

    raw_bytes = output_exe_path.read_bytes()
    sha256 = hashlib.sha256(raw_bytes).hexdigest()

    return WindowsInstallerPackageResult(
        output_path=output_exe_path,
        file_size_bytes=len(raw_bytes),
        sha256_hash=sha256,
        manifest=manifest,
    )
