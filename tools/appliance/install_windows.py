#!/usr/bin/env python3
"""ComputeMesh Windows Local Client Installer Script."""
from __future__ import annotations

import os
from pathlib import Path
import shutil
import subprocess
import sys
import winreg

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from config import CONFIG

def install():
    local_app_data = os.environ.get("LOCALAPPDATA", str(Path.home() / "AppData" / "Local"))
    install_dir = Path(local_app_data) / "Programs" / "ComputeMesh"
    install_dir.mkdir(parents=True, exist_ok=True)
    
    source_exe = REPO_ROOT / "dist" / "ComputeMesh-Setup-x64.exe"
    if not source_exe.exists():
        source_exe = REPO_ROOT / "portal" / "downloads" / "ComputeMesh-Setup-x64.exe"
    
    target_exe = install_dir / "ComputeMesh.exe"
    source_ico = REPO_ROOT / "tools" / "appliance" / "computemesh.ico"
    target_ico = install_dir / "computemesh.ico"
    
    # Terminate any running ComputeMesh instance before replacing
    try:
        subprocess.run(["taskkill", "/F", "/IM", "ComputeMesh.exe"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except Exception:
        pass
    
    import time
    time.sleep(1.0)
    
    print(f"Copying {source_exe} -> {target_exe}...")
    copied = False
    for attempt in range(5):
        try:
            shutil.copy2(source_exe, target_exe)
            copied = True
            break
        except PermissionError:
            time.sleep(0.8)
    
    if not copied:
        shutil.copy2(source_exe, target_exe)
    
    if source_ico.exists():
        shutil.copy2(source_ico, target_ico)
        print(f"Copied icon to {target_ico}")
        
    # Windows Registry - Autostart
    try:
        run_key_path = r"Software\Microsoft\Windows\CurrentVersion\Run"
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, run_key_path, 0, winreg.KEY_SET_VALUE) as key:
            winreg.SetValueEx(key, "ComputeMesh", 0, winreg.REG_SZ, f'"{target_exe}" --tray')
        print("Registry HKCU Run configured.")
    except Exception as e:
        print(f"Warning setting Run registry: {e}")

    # Windows Registry - Uninstall entry
    try:
        uninstall_path = r"Software\Microsoft\Windows\CurrentVersion\Uninstall\ComputeMesh"
        with winreg.CreateKey(winreg.HKEY_CURRENT_USER, uninstall_path) as key:
            winreg.SetValueEx(key, "DisplayName", 0, winreg.REG_SZ, "ComputeMesh Provider Agent")
            winreg.SetValueEx(key, "DisplayVersion", 0, winreg.REG_SZ, CONFIG.appliance_version)
            winreg.SetValueEx(key, "Publisher", 0, winreg.REG_SZ, "ComputeMesh Network Foundation")
            winreg.SetValueEx(key, "DisplayIcon", 0, winreg.REG_SZ, str(target_ico))
            winreg.SetValueEx(key, "InstallLocation", 0, winreg.REG_SZ, str(install_dir))
        print("Registry HKCU Uninstall entry created.")
    except Exception as e:
        print(f"Warning setting Uninstall registry: {e}")

    # Shortcuts
    try:
        ps_script = f"""
$wsh = New-Object -ComObject WScript.Shell
$startDir = "$env:APPDATA\\Microsoft\\Windows\\Start Menu\\Programs"
$s1 = $wsh.CreateShortcut("$startDir\\ComputeMesh.lnk")
$s1.TargetPath = "{target_exe}"
$s1.WorkingDirectory = "{install_dir}"
$s1.IconLocation = "{target_ico},0"
$s1.Description = "ComputeMesh Provider Agent"
$s1.Save()

$deskDir = "$env:USERPROFILE\\Desktop"
$s2 = $wsh.CreateShortcut("$deskDir\\ComputeMesh.lnk")
$s2.TargetPath = "{target_exe}"
$s2.WorkingDirectory = "{install_dir}"
$s2.IconLocation = "{target_ico},0"
$s2.Description = "ComputeMesh Provider Agent"
$s2.Save()
"""
        subprocess.run(["powershell", "-NoProfile", "-Command", ps_script], check=True)
        print("Created Desktop and Start Menu shortcuts.")
    except Exception as e:
        print(f"Warning creating shortcuts: {e}")

    # Launch interactive desktop app immediately after install
    try:
        subprocess.Popen(["explorer.exe", str(target_exe)])
        print("Launched ComputeMesh in user interactive desktop session.")
    except Exception as e:
        print(f"Warning auto-launching app: {e}")

    print(f"\n[OK] ComputeMesh v{CONFIG.appliance_version} successfully installed on this PC!")
    print(f"Location: {target_exe}")

if __name__ == "__main__":
    install()
