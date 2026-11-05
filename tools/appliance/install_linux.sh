#!/usr/bin/env bash
# SPDX-License-Identifier: Apache-2.0
# ComputeMesh Debian/Linux Node Service & Tray Installer
set -euo pipefail

echo "========================================================"
echo "  ComputeMesh Provider Node Installer (Debian/Ubuntu)  "
echo "========================================================"

TARGET_DIR="/opt/computemesh"
SERVICE_NAME="computemesh-node"
SERVICE_FILE="${TARGET_DIR}/tools/appliance/deploy/${SERVICE_NAME}.service"
SYSTEMD_DEST="/etc/systemd/system/${SERVICE_NAME}.service"

# Check root/sudo for service installation
IS_ROOT=false
if [ "$(id -u)" -eq 0 ]; then
    IS_ROOT=true
fi

echo "[*] Step 1: Checking and installing runtime prerequisites..."
if command -v apt-get >/dev/null 2>&1; then
    if [ "$IS_ROOT" = true ]; then
        apt-get update -qq
        apt-get install -y -qq python3 python3-pip python3-pil python3-pystray xdg-utils curl
    else
        sudo apt-get update -qq
        sudo apt-get install -y -qq python3 python3-pip python3-pil python3-pystray xdg-utils curl
    fi
elif command -v dnf >/dev/null 2>&1; then
    sudo dnf install -y -q python3 python3-pip python3-pillow python3-pystray xdg-utils curl
fi

echo "[*] Step 2: Setting up deployment directory at ${TARGET_DIR}..."
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SOURCE_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"

if [ "$IS_ROOT" = true ]; then
    mkdir -p "${TARGET_DIR}"
    cp -r "${SOURCE_ROOT}"/* "${TARGET_DIR}/"
else
    sudo mkdir -p "${TARGET_DIR}"
    sudo cp -r "${SOURCE_ROOT}"/* "${TARGET_DIR}/"
fi

echo "[*] Step 3: Registering systemd service ${SERVICE_NAME}..."
if [ -f "${SERVICE_FILE}" ]; then
    if [ "$IS_ROOT" = true ]; then
        cp "${SERVICE_FILE}" "${SYSTEMD_DEST}"
        systemctl daemon-reload
        systemctl enable "${SERVICE_NAME}"
        systemctl restart "${SERVICE_NAME}"
    else
        sudo cp "${SERVICE_FILE}" "${SYSTEMD_DEST}"
        sudo systemctl daemon-reload
        sudo systemctl enable "${SERVICE_NAME}"
        sudo systemctl restart "${SERVICE_NAME}"
    fi
    echo "[+] Service ${SERVICE_NAME} enabled and started via systemd."
else
    echo "[!] Warning: Service file ${SERVICE_FILE} not found."
fi

echo "[*] Step 4: Configuring Desktop Autostart for System Tray..."
CURRENT_USER="${SUDO_USER:-$USER}"
USER_HOME=$(getent passwd "$CURRENT_USER" | cut -d: -f6)
AUTOSTART_DIR="${USER_HOME}/.config/autostart"
mkdir -p "${AUTOSTART_DIR}"
cat <<EOF > "${AUTOSTART_DIR}/computemesh-tray.desktop"
[Desktop Entry]
Type=Application
Name=ComputeMesh Provider Node
Exec=/usr/bin/python3 ${TARGET_DIR}/tools/appliance/linux_tray_app.py --tray
Icon=${TARGET_DIR}/portal/assets/computemesh.png
Terminal=false
Categories=Utility;Network;
X-GNOME-Autostart-enabled=true
EOF
chown -R "${CURRENT_USER}:${CURRENT_USER}" "${AUTOSTART_DIR}"

echo ""
echo "========================================================"
echo "  [SUCCESS] ComputeMesh Node is installed & active!    "
echo "  - Service Status: systemctl status ${SERVICE_NAME}    "
echo "  - Web Dashboard:  http://localhost:8080/agent         "
echo "  - AI Chat Studio: http://localhost:8080/webui/        "
echo "========================================================"
