@echo off
cd /d "%~dp0.."
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0evidence.ps1" -Mode export
if errorlevel 1 pause
