# -*- mode: python ; coding: utf-8 -*-


a = Analysis(
    ['tools/appliance/windows_tray_app.py'],
    pathex=['.'],
    binaries=[],
    datas=[('services', 'services'), ('tools/appliance', 'tools/appliance'), ('tools/security', 'tools/security'), ('portal/assets', 'portal/assets')],
    hiddenimports=['services', 'services.appliance_dashboard', 'services.appliance_dashboard.server', 'services.updater', 'services.updater.auto_updater', 'services.billing', 'services.billing.ledger', 'tools', 'tools.appliance', 'tools.appliance.hardware_detector', 'tools.appliance.appliance_config', 'tools.security', 'tools.security.ed25519_verify', 'tools.security.signing_keys', 'PIL', 'PIL.ImageTk', 'PIL.ImageDraw', 'pystray'],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
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
