@echo off
cd /d "%~dp0.."
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0setup.ps1" -Mode network-server
if errorlevel 1 pause
