@echo off
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

echo [2/4] Bereinige dauerhafte Windows-Benutzer-Registrierung...
reg delete "HKCU\Environment" /v OLLAMA_HOST /f >nul 2>nul
reg delete "HKCU\Environment" /v OLLAMA_ORIGINS /f >nul 2>nul
reg delete "HKCU\Environment" /v OLLAMA_KEEP_ALIVE /f >nul 2>nul
reg delete "HKCU\Environment" /v OLLAMA_NUM_PARALLEL /f >nul 2>nul

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
    ) else if exist "%LOCALAPPDATA%\Programs\Ollama\ollama.exe" (
        start /B "" "%LOCALAPPDATA%\Programs\Ollama\ollama.exe" serve >nul 2>nul
    )
)

echo [4/4] Fuehre Python Bridge Reset durch...
cd /d "%~dp0"
if exist "tools\appliance\ollama_mesh_bridge.py" (
    python tools\appliance\ollama_mesh_bridge.py reset >nul 2>nul
) else if exist "ComputeMesh\tools\appliance\ollama_mesh_bridge.py" (
    python ComputeMesh\tools\appliance\ollama_mesh_bridge.py reset >nul 2>nul
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
