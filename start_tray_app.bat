@echo off
:: ComputeMesh Windows System Tray App Launcher
setlocal EnableDelayedExpansion
cd /d "%~dp0"

set "PYTHON_EXE=pythonw.exe"
if exist "C:\Users\frede\AppData\Local\Programs\Python\Python311\pythonw.exe" (
    set "PYTHON_EXE=C:\Users\frede\AppData\Local\Programs\Python\Python311\pythonw.exe"
)

start "" "%PYTHON_EXE%" tools\appliance\windows_tray_app.py
exit /b 0
