@echo off
setlocal
cd /d "%~dp0"
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0setup\setup.ps1" -Mode menu
if errorlevel 1 pause
