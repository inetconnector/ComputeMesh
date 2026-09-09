# -*- mode: python ; coding: utf-8 -*-

from pathlib import Path
import sys


_tcl_root = Path(sys.base_prefix) / 'tcl'
_tcl_dir = next(path for path in sorted(_tcl_root.glob('tcl*'), reverse=True) if path.is_dir())
_tk_dir = next(path for path in sorted(_tcl_root.glob('tk*'), reverse=True) if path.is_dir())


a = Analysis(
    ['tools/appliance/windows_tray_app.py'],
    pathex=['.'],
    binaries=[],
    datas=[('config.py', '.'), ('services', 'services'), ('tools/appliance', 'tools/appliance'), ('tools/security', 'tools/security'), ('portal/assets', 'portal/assets'), (str(_tcl_dir), '_tcl_data'), (str(_tk_dir), '_tk_data')],
    hiddenimports=['config', 'services.common', 'services.common.config', 'services', 'services.appliance_dashboard', 'services.appliance_dashboard.server', 'services.appliance_dashboard.template_loader', 'services.appliance_dashboard.network', 'services.appliance_dashboard.mesh_aggregator', 'services.appliance_dashboard.tunnel_relay', 'services.updater', 'services.updater.auto_updater', 'services.billing', 'services.billing.ledger', 'tools', 'tools.appliance', 'tools.appliance.hardware_detector', 'tools.appliance.appliance_config', 'tools.appliance.token_metering', 'tools.appliance.lan_discovery_responder', 'tools.security', 'tools.security.ed25519_verify', 'tools.security.signing_keys', 'PIL', 'PIL.ImageTk', 'PIL.ImageDraw', 'PIL.IcoImagePlugin', 'PIL.PngImagePlugin', 'pystray', 'pystray._win32', 'pystray._util', 'pystray._util.win32', 'win32gui', 'win32con', 'win32api'],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=['deploy/windows/pyi_rth_tkinter.py'],
    excludes=[],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name='ComputeMesh-Setup-x64',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=['tools/appliance/computemesh.ico'],
)
