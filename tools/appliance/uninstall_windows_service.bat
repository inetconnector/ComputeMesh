@echo off
:: ComputeMesh Windows Service Uninstaller (UAC Elevation Support)
setlocal EnableDelayedExpansion

net session >nul 2>&1
if %errorlevel% neq 0 (
    echo [*] Administrator-Rechte erforderlich. Fordere UAC-Erhoehung an...
    powershell -NoProfile -ExecutionPolicy Bypass -Command "Start-Process cmd -ArgumentList '/c \"\"%~f0\"\"' -Verb RunAs"
    exit /b
)

title ComputeMesh Windows Service Uninstaller
echo ========================================================
echo   ComputeMesh Windows Service Deinstallation
echo ========================================================
echo.

set "SCRIPT_DIR=%~dp0"
set "PYTHON_EXE=C:\Users\frede\AppData\Local\Programs\Python\Python311\python.exe"
if not exist "%PYTHON_EXE%" (
    set "PYTHON_EXE=python.exe"
)

echo [*] Stoppe und entferne Windows-Dienst 'ComputeMeshNode'...
"%PYTHON_EXE%" "%SCRIPT_DIR%windows_service.py" --uninstall

echo.
echo ========================================================
echo   Dienst erfolgreich deinstalliert.
echo ========================================================
pause
