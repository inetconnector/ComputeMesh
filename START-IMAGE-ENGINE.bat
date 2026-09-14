@echo off
setlocal

echo ========================================================
echo  ComputeMesh High-Performance Image Engine (sd.cpp CUDA)
echo ========================================================

set "SCRIPT_DIR=%~dp0"
set "BIN=%SCRIPT_DIR%runtime\sd_cpp\bin\sd-server.exe"

if not exist "%BIN%" (
    if exist "%SCRIPT_DIR%runtime\sd_cpp\build_ninja\bin\sd-server.exe" (
        set "BIN=%SCRIPT_DIR%runtime\sd_cpp\build_ninja\bin\sd-server.exe"
    ) else if exist "%SCRIPT_DIR%runtime\sd_cpp\build_ninja\sd-server.exe" (
        set "BIN=%SCRIPT_DIR%runtime\sd_cpp\build_ninja\sd-server.exe"
    ) else if exist "%SCRIPT_DIR%runtime\sd_cpp\build_nmake\bin\sd-server.exe" (
        set "BIN=%SCRIPT_DIR%runtime\sd_cpp\build_nmake\bin\sd-server.exe"
    ) else if exist "%SCRIPT_DIR%runtime\sd_cpp\build_nmake\sd-server.exe" (
        set "BIN=%SCRIPT_DIR%runtime\sd_cpp\build_nmake\sd-server.exe"
    )
)

if not exist "%BIN%" (
    echo [INFO] sd-server binary not found. Starting automatic CUDA build...
    call "%SCRIPT_DIR%runtime\sd_cpp\build_cuda.bat"
)

echo [INFO] Launching ComputeMesh Image Engine Service on Port 8085...
py -3 "%SCRIPT_DIR%runtime\sd_cpp\image_engine_service.py" %*

pause
