@echo off
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

echo [2/3] Pruefe und starte lokalen Ollama-Dienst...
tasklist /FI "IMAGENAME eq ollama.exe" 2>NUL | find /I /N "ollama.exe">NUL
if "%ERRORLEVEL%"=="0" (
    echo   ✓ Ollama laeuft bereits auf Port 11434.
) else (
    echo   -> Starte Ollama Daemon im Hintergrund...
    where ollama >nul 2>nul
    if "%ERRORLEVEL%"=="0" (
        start /B "" ollama serve >nul 2>nul
    ) else if exist "%LOCALAPPDATA%\Programs\Ollama\ollama.exe" (
        start /B "" "%LOCALAPPDATA%\Programs\Ollama\ollama.exe" serve >nul 2>nul
    ) else (
        echo   [!] Hinweis: ollama.exe nicht im Standardpfad gefunden.
        echo       Bitte installiere Ollama von https://ollama.com falls noch nicht vorhanden.
    )
)

echo.
echo [3/3] Starte ComputeMesh Provider Daemon...
cd /d "%~dp0"
if exist "tools\appliance\windows_tray_app.py" (
    start "" python tools\appliance\windows_tray_app.py
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
echo  * Ungenutzte GPU-Kapazitaet wird im Leerlauf automatisch im
echo    ComputeMesh-Netzwerk monetarisiert und in Credits verguetet!
echo.
echo  * Um Ollama wieder auf den Ursprungszustand zurueckzusetzen,
echo    fuehre einfach 'OLLAMA-RESET-DEFAULT.bat' aus.
echo.
pause
