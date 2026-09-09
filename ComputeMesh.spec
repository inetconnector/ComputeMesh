# -*- mode: python ; coding: utf-8 -*-

from pathlib import Path
import sys


_tcl_root = Path(sys.base_prefix) / 'tcl'
_tcl_dir = next(path for path in sorted(_tcl_root.glob('tcl*'), reverse=True) if path.is_dir())
_tk_dir = next(path for path in sorted(_tcl_root.glob('tk*'), reverse=True) if path.is_dir())


a = Analysis(
    ['tools/appliance/windows_tray_app.py'],
    pathex=[],
    binaries=[],
    datas=[('services/appliance_dashboard/static', 'services/appliance_dashboard/static'), ('services/common', 'services/common'), (str(_tcl_dir), '_tcl_data'), (str(_tk_dir), '_tk_data')],
    hiddenimports=['PIL', 'PIL.Image', 'pystray', 'tkinter', 'urllib.request'],
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
    [],
    exclude_binaries=True,
    name='ComputeMesh',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=['assets/icon.ico'],
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='ComputeMesh',
)
