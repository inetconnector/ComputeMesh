#!/usr/bin/env bash
set -e

echo "========================================================"
echo " ComputeMesh High-Performance Image Engine (Linux CUDA) "
echo "========================================================"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BIN="$SCRIPT_DIR/runtime/sd_cpp/bin/sd-server"

if [ ! -f "$BIN" ]; then
    if [ -f "$SCRIPT_DIR/runtime/sd_cpp/build_linux/bin/sd-server" ]; then
        BIN="$SCRIPT_DIR/runtime/sd_cpp/build_linux/bin/sd-server"
    elif [ -f "$SCRIPT_DIR/runtime/sd_cpp/build_linux/sd-server" ]; then
        BIN="$SCRIPT_DIR/runtime/sd_cpp/build_linux/sd-server"
    fi
fi

if [ ! -f "$BIN" ]; then
    echo "[INFO] sd-server binary not found. Running build_linux.sh..."
    bash "$SCRIPT_DIR/runtime/sd_cpp/build_linux.sh"
fi

echo "[INFO] Starting ComputeMesh Image Engine Service on Port 8085..."
python3 "$SCRIPT_DIR/runtime/sd_cpp/image_engine_service.py" "$@"
