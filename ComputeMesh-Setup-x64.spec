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
    hiddenimports=[
        'config', 'services.common', 'services.common.config', 'services',
        'services.appliance_dashboard', 'services.appliance_dashboard.server',
        'services.appliance_dashboard.inference_router', 'services.appliance_dashboard.system_actions',
        'services.appliance_dashboard.killswitch_actions', 'services.appliance_dashboard.telemetry_handler',
        'services.appliance_dashboard.webapp_handler',
        'services.appliance_dashboard.template_loader', 'services.appliance_dashboard.network',
        'services.appliance_dashboard.mesh_aggregator', 'services.appliance_dashboard.tunnel_relay',
        'services.mcp', 'services.mcp.config', 'services.mcp.mcp_client', 'services.mcp.mcp_http_client',
        'services.mcp.tool_registry', 'services.mcp.agent_loop', 'services.mcp.builtin',
        'services.mcp.builtin.webapp_deployer',
        'services.mcp.builtin.code_patch_engine', 'services.mcp.builtin.code_search_indexer',
        'services.mcp.builtin.code_lint_and_syntax', 'services.mcp.builtin.test_runner_tools',
        'services.mcp.builtin.git_tools', 'services.mcp.builtin.system_tools',
        'services.mcp.builtin.file_system_tools', 'services.mcp.builtin.data_table_tools',
        'services.mcp.builtin.document_reader', 'services.mcp.builtin.audio_tools',
        'services.mcp.builtin.python_sandbox', 'services.mcp.builtin.python_calc',
        'services.mcp.builtin.generate_image', 'services.mcp.builtin.weather',
        'services.mcp.builtin.weather_forecast', 'services.mcp.builtin.web_search',
        'services.mcp.builtin.web_fetch', 'services.mcp.builtin.wikipedia',
        'services.mcp.builtin.multilingual_wiki', 'services.mcp.builtin.knowledge_fusion',
        'services.mcp.builtin.timeline_builder', 'services.mcp.builtin.fact_triangulation',
        'services.mcp.builtin.url_security', 'services.mcp.builtin.currency',
        'services.mcp.builtin.geo_routing', 'services.mcp.builtin.news_feed',
        'services.mcp.builtin.events', 'services.mcp.builtin.places',
        'services.mcp.builtin.time_calendar', 'services.mcp.builtin.company_lookup',
        'services.mcp.builtin.package_registry', 'services.mcp.builtin.arxiv_research',
        'services.mcp.builtin.food_products', 'services.mcp.builtin.chemical_data',
        'services.mcp.builtin.world_bank', 'services.mcp.builtin.sports_data',
        'services.mcp.builtin.dictionary_lookup', 'services.mcp.builtin.train_transit',
        'services.mcp.builtin.earthquake_feed', 'services.mcp.builtin.network_tools',
        'services.mcp.builtin.github_client', 'services.mcp.builtin.github_repo_tools',
        'services.mcp.builtin.github_issue_tools', 'services.mcp.builtin.github_pr_tools',
        'services.mcp.builtin.github_ci_tools', 'services.mcp.builtin.terminal_runner',
        'services.mcp.builtin.http_api_client',
        'services.mcp.builtin.workspace_quarantine', 'services.mcp.builtin.workspace_doctor',
        'services.mcp.builtin.mission_journal', 'services.mcp.builtin.tool_installer',
        'services.mcp.builtin.adb_bridge_tools',
        'services.mcp.builtin.rag_tool', 'services.rag.document_parser', 'services.rag.chunker',
        'services.rag.embeddings', 'services.rag.vector_store',
        'services.grammar.json_schema_to_gbnf', 'services.memory.user_memory',
        'services.voice.voice_realtime',
        'services.updater', 'services.updater.auto_updater', 'services.billing', 'services.billing.ledger',
        'tools', 'tools.appliance', 'tools.appliance.hardware_detector', 'tools.appliance.appliance_config',
        'tools.appliance.token_metering', 'tools.appliance.lan_discovery_responder',
        'tools.security', 'tools.security.ed25519_verify', 'tools.security.signing_keys', 'tools.security.release_signer',
        'PIL', 'PIL.ImageTk', 'PIL.ImageDraw', 'PIL.IcoImagePlugin', 'PIL.PngImagePlugin',
        'pystray', 'pystray._win32', 'pystray._util', 'pystray._util.win32',
        'win32gui', 'win32con', 'win32api'
    ],
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
