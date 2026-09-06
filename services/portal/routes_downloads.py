"""ComputeMesh Dynamic Script & Configuration Generator for Fleet Operators & Node Providers.

Generates pre-configured 1-click launch and reset scripts for Windows, Linux, and macOS
with embedded owner keys, enrollment tokens, and cluster endpoints.
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Any

DEFAULT_CLUSTER_URL = "https://mesh.inetconnector.com"


def build_ollama_starter_bat(owner_key: str = "", cluster_url: str = DEFAULT_CLUSTER_URL) -> str:
    """Generates a personalized Windows Batch launcher for Ollama + ComputeMesh pooling."""
    safe_key = owner_key.strip() if owner_key else "IHR_OWNER_KEY_HIER"
    return f"""@echo off
chcp 65001 >nul
title ComputeMesh - Ollama Mesh-Pool Starter
color 0B

echo ======================================================================
echo    ComputeMesh ^& Ollama Dynamic Mesh-Pool Launcher
echo ======================================================================
echo.
echo [1/3] Konfiguriere Ollama fuer ComputeMesh Mesh-Pooling...
set OLLAMA_HOST=0.0.0.0:11434
set OLLAMA_ORIGINS=*
set OLLAMA_KEEP_ALIVE=24h
set OLLAMA_NUM_PARALLEL=4
set COMPUTEMESH_OWNER_KEY={safe_key}
set COMPUTEMESH_CLUSTER_URL={cluster_url}

echo [2/3] Pruefe und starte lokalen Ollama-Dienst...
tasklist /FI "IMAGENAME eq ollama.exe" 2>NUL | find /I /N "ollama.exe">NUL
if "%ERRORLEVEL%"=="0" (
    echo   ✓ Ollama laeuft bereits auf Port 11434.
) else (
    echo   -> Starte Ollama Daemon im Hintergrund...
    where ollama >nul 2>nul
    if "%ERRORLEVEL%"=="0" (
        start /B "" ollama serve >nul 2>nul
    ) else if exist "%LOCALAPPDATA%\\Programs\\Ollama\\ollama.exe" (
        start /B "" "%LOCALAPPDATA%\\Programs\\Ollama\\ollama.exe" serve >nul 2>nul
    ) else (
        echo   [!] Hinweis: ollama.exe nicht im Standardpfad gefunden.
        echo       Bitte installiere Ollama von https://ollama.com falls noch nicht vorhanden.
    )
)

echo.
echo [3/3] Starte ComputeMesh Provider Daemon...
cd /d "%~dp0"
if exist "ComputeMesh\\tools\\appliance\\windows_tray_app.py" (
    start "" python ComputeMesh\\tools\\appliance\\windows_tray_app.py --owner-key %COMPUTEMESH_OWNER_KEY%
) else if exist "tools\\appliance\\windows_tray_app.py" (
    start "" python tools\\appliance\\windows_tray_app.py --owner-key %COMPUTEMESH_OWNER_KEY%
) else if exist "START-ALL.bat" (
    start "" START-ALL.bat
)

echo.
echo ======================================================================
echo  ✓ ComputeMesh ^& Ollama Mesh-Pool erfolgreich gestartet!
echo ======================================================================
echo.
echo  * Eigener Rechner hat 100%% Vorrang fuer lokale Entwickler-Tools:
echo      - LocalCode, VS Code, Cursor, Cline, Ollama CLI
echo      - Lokale URL: http://127.0.0.1:11434
echo.
echo  * Cluster-Zuordnung: {cluster_url}
echo  * Owner Key: {safe_key[:12]}...
echo.
echo  * Ungenutzte GPU-Kapazitaet wird im Leerlauf automatisch im
echo    ComputeMesh-Netzwerk monetarisiert und in Credits verguetet!
echo.
echo  * Um Ollama wieder auf den Ursprungszustand zurueckzusetzen,
echo    fuehre einfach 'OLLAMA-RESET-DEFAULT.bat' aus.
echo.
pause
"""


def build_ollama_reset_bat() -> str:
    """Generates the Windows Batch reset script returning Ollama to standard standalone mode."""
    return """@echo off
chcp 65001 >nul
title ComputeMesh - Ollama Reset auf Ursprungszustand
color 0A

echo ======================================================================
echo    ComputeMesh - Ollama Reset auf Standard-Ursprungszustand
echo ======================================================================
echo.
echo [1/4] Bereinige temporaere Umgebungsvariablen (Session)...
set OLLAMA_HOST=
set OLLAMA_ORIGINS=
set OLLAMA_KEEP_ALIVE=
set OLLAMA_NUM_PARALLEL=
set COMPUTEMESH_OWNER_KEY=
set COMPUTEMESH_CLUSTER_URL=

echo [2/4] Bereinige dauerhafte Windows-Benutzer-Registrierung...
reg delete "HKCU\\Environment" /v OLLAMA_HOST /f >nul 2>nul
reg delete "HKCU\\Environment" /v OLLAMA_ORIGINS /f >nul 2>nul
reg delete "HKCU\\Environment" /v OLLAMA_KEEP_ALIVE /f >nul 2>nul
reg delete "HKCU\\Environment" /v OLLAMA_NUM_PARALLEL /f >nul 2>nul

echo [3/4] Starte Ollama mit Standard-Konfiguration neu...
tasklist /FI "IMAGENAME eq ollama.exe" 2>NUL | find /I /N "ollama.exe">NUL
if "%ERRORLEVEL%"=="0" (
    echo   -> Beende laufende Ollama-Instanz...
    taskkill /F /IM ollama.exe >nul 2>nul
    timeout /T 1 /NOBREAK >nul
    echo   -> Starte Ollama im Standard-Standalone-Modus neu...
    where ollama >nul 2>nul
    if "%ERRORLEVEL%"=="0" (
        start /B "" ollama serve >nul 2>nul
    ) else if exist "%LOCALAPPDATA%\\Programs\\Ollama\\ollama.exe" (
        start /B "" "%LOCALAPPDATA%\\Programs\\Ollama\\ollama.exe" serve >nul 2>nul
    )
)

echo [4/4] Fuehre Python Bridge Reset durch...
cd /d "%~dp0"
if exist "tools\\appliance\\ollama_mesh_bridge.py" (
    python tools\\appliance\\ollama_mesh_bridge.py reset >nul 2>nul
) else if exist "ComputeMesh\\tools\\appliance\\ollama_mesh_bridge.py" (
    python ComputeMesh\\tools\\appliance\\ollama_mesh_bridge.py reset >nul 2>nul
)

echo.
echo ======================================================================
echo  ✓ Ollama wurde erfolgreich auf den Standard-Ursprungszustand zurueckgesetzt!
echo ======================================================================
echo.
echo  * Standard-Einstellungen sind wieder aktiv:
echo      - Host: 127.0.0.1:11434 (ausschliesslich lokaler Loopback)
echo      - Standard CORS / Origins (nur lokale Aufrufe)
echo      - Standard Model-Unload-Timeout (5 Minuten)
echo.
echo  * Dein lokales System ist vollstaendig vom Mesh-Pool entkoppelt.
echo    Ollama verhaelt sich exakt wie vor dem Start des Mesh-Pools.
echo.
pause
"""


def build_ollama_starter_sh(owner_key: str = "", cluster_url: str = DEFAULT_CLUSTER_URL) -> str:
    """Generates a personalized Linux/macOS shell script for Ollama + ComputeMesh pooling."""
    safe_key = owner_key.strip() if owner_key else "IHR_OWNER_KEY_HIER"
    return f"""#!/usr/bin/env bash
set -e

echo "======================================================================"
echo "   ComputeMesh & Ollama Dynamic Mesh-Pool Launcher (Linux / macOS)"
echo "======================================================================"
echo ""

export OLLAMA_HOST="0.0.0.0:11434"
export OLLAMA_ORIGINS="*"
export OLLAMA_KEEP_ALIVE="24h"
export OLLAMA_NUM_PARALLEL="4"
export COMPUTEMESH_OWNER_KEY="{safe_key}"
export COMPUTEMESH_CLUSTER_URL="{cluster_url}"

echo "[1/3] Prüfe und starte lokalen Ollama-Dienst..."
if pgrep -x "ollama" > /dev/null 2>&1; then
    echo "  ✓ Ollama läuft bereits auf Port 11434."
else
    echo "  -> Starte Ollama Daemon im Hintergrund..."
    if command -v ollama > /dev/null 2>&1; then
        ollama serve > /dev/null 2>&1 &
        sleep 2
    else
        echo "  [!] Hinweis: ollama executable nicht gefunden. Bitte von https://ollama.com installieren."
    fi
fi

echo ""
echo "[2/3] Konfiguration aktiv:"
echo "  - Host: 0.0.0.0:11434 (Mesh-Pooling aktiviert)"
echo "  - Cluster URL: ${{COMPUTEMESH_CLUSTER_URL}}"
echo "  - Owner Key: ${{COMPUTEMESH_OWNER_KEY:0:12}}..."
echo ""
echo "[3/3] Starte ComputeMesh Node Connector..."
if [ -f "tools/appliance/node_daemon.py" ]; then
    python3 tools/appliance/node_daemon.py --owner-key "$COMPUTEMESH_OWNER_KEY" &
elif [ -f "ComputeMesh/tools/appliance/node_daemon.py" ]; then
    python3 ComputeMesh/tools/appliance/node_daemon.py --owner-key "$COMPUTEMESH_OWNER_KEY" &
fi

echo ""
echo "======================================================================"
echo " ✓ ComputeMesh & Ollama Mesh-Pool erfolgreich gestartet!"
echo "======================================================================"
echo ""
echo " * Eigener Rechner hat 100% Vorrang für lokale Entwickler-Tools."
echo " * Ungenutzte GPU-Kapazität wird im Leerlauf automatisch vergütet."
echo " * Zum Zurücksetzen führe 'ollama-reset-default.sh' aus."
echo ""
"""


def build_ollama_reset_sh() -> str:
    """Generates a Linux/macOS shell reset script returning Ollama to standard standalone mode."""
    return """#!/usr/bin/env bash
set -e

echo "======================================================================"
echo "   ComputeMesh - Ollama Reset auf Standard-Ursprungszustand (Linux/macOS)"
echo "======================================================================"
echo ""

echo "[1/3] Bereinige Umgebungsvariablen..."
unset OLLAMA_HOST
unset OLLAMA_ORIGINS
unset OLLAMA_KEEP_ALIVE
unset OLLAMA_NUM_PARALLEL
unset COMPUTEMESH_OWNER_KEY
unset COMPUTEMESH_CLUSTER_URL

echo "[2/3] Starte Ollama im Standard-Modus neu..."
if pgrep -x "ollama" > /dev/null 2>&1; then
    pkill -f "ollama" || true
    sleep 1
    if command -v ollama > /dev/null 2>&1; then
        ollama serve > /dev/null 2>&1 &
    fi
fi

echo ""
echo "======================================================================"
echo " ✓ Ollama wurde erfolgreich auf den Standard-Ursprungszustand zurückgesetzt!"
echo "======================================================================"
echo " * Standard Host: 127.0.0.1:11434 (nur lokaler Loopback)"
echo " * Standard Model-Unload-Timeout aktiv."
echo ""
"""


def get_download_file_response(
    script_type: str,
    os_target: str,
    owner_key: str = "",
    cluster_url: str = DEFAULT_CLUSTER_URL,
) -> tuple[str, str, str]:
    """Returns (file_content, filename, content_type)."""
    os_target = os_target.lower().strip()
    script_type = script_type.lower().strip()

    if script_type in ("reset", "ollama-reset", "reset-default"):
        if os_target in ("linux", "mac", "macos", "sh", "bash"):
            return build_ollama_reset_sh(), "ollama-reset-default.sh", "application/x-sh"
        return build_ollama_reset_bat(), "OLLAMA-RESET-DEFAULT.bat", "application/x-bat"

    # Default: starter script
    if os_target in ("linux", "mac", "macos", "sh", "bash"):
        return build_ollama_starter_sh(owner_key, cluster_url), "ollama-mesh-start.sh", "application/x-sh"
    return build_ollama_starter_bat(owner_key, cluster_url), "OLLAMA-MESH-START.bat", "application/x-bat"
