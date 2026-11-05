@echo off
:: ComputeMesh Windows Service Installer (UAC Elevation Support)
setlocal EnableDelayedExpansion

net session >nul 2>&1
if %errorlevel% neq 0 (
    echo [*] Administrator-Rechte erforderlich. Fordere UAC-Erhoehung an...
    powershell -NoProfile -ExecutionPolicy Bypass -Command "Start-Process cmd -ArgumentList '/c \"\"%~f0\"\"' -Verb RunAs"
    exit /b
)

title ComputeMesh Windows Service Installer
echo ========================================================
echo   ComputeMesh Windows Service Installer (ComputeMeshNode)
echo ========================================================
echo.

set "SCRIPT_DIR=%~dp0"
set "PYTHON_EXE=C:\Users\frede\AppData\Local\Programs\Python\Python311\python.exe"
if not exist "%PYTHON_EXE%" (
    set "PYTHON_EXE=python.exe"
)

echo [*] Registriere Windows-Dienst 'ComputeMeshNode'...
"%PYTHON_EXE%" "%SCRIPT_DIR%windows_service.py" --install

echo.
echo [*] Starte Windows-Dienst 'ComputeMeshNode'...
sc.exe start ComputeMeshNode

echo.
echo [*] Status des Dienstes pruefen:
sc.exe query ComputeMeshNode

echo.
echo ========================================================
echo   Fertig! Der Dienst laeuft jetzt im Hintergrund.
echo   Web-Dashboard: http://localhost:8080/agent
echo ========================================================
pause
