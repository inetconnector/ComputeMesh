#!/usr/bin/env bash
# ==============================================================================
# ComputeMesh NodeOS: Automated Appliance Installer (Native AMD + NVIDIA Support)
# Supports: Mixed NVIDIA + AMD rigs, HiveOS, Ubuntu 22.04/24.04, Debian 12/13.
# Usage: curl -fsSL https://get.computemesh.net/install.sh | sudo bash
# ==============================================================================

set -euo pipefail

RED='\033[0;31m'
GREEN='\033[0;32m'
CYAN='\033[0;36m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

echo -e "${CYAN}"
cat << "EOF"
  ____                            _         __  __           _     
 / ___|___  _ __ ___  _ __  _   _| |_ ___  |  \/  | ___  ___| |__  
| |   / _ \| '_ ` _ \| '_ \| | | | __/ _ \ | |\/| |/ _ \/ __| '_ \ 
| |__| (_) | | | | | | |_) | |_| | ||  __/ | |  | |  __/\__ \ | | |
 \____\___/|_| |_| |_| .__/ \__,_|\__\___| |_|  |_|\___||___/_| |_|
                     |_|  NodeOS Provider Appliance (AMD + NVIDIA Native)
EOF
echo -e "${NC}"

if [ "$(id -u)" -ne 0 ]; then
    echo -e "${RED}[ERROR] This installer must be run as root (use sudo).${NC}"
    exit 1
fi

echo -e "${GREEN}[1/6] Detecting operating system and GPU hardware...${NC}"
IS_HIVEOS=false
if [ -f /hive/bin/hive ] || [ -d /hive-config ]; then
    IS_HIVEOS=true
    echo -e "${YELLOW}--> HiveOS environment detected! Applying non-destructive coexistence mode.${NC}"
fi

# Detect GPU Vendors via lspci
HAS_NVIDIA=false
HAS_AMD=false
HAS_INTEL=false

if lspci -nn | grep -Ei "vga|3d|display" | grep -qi "10de:"; then
    HAS_NVIDIA=true
    echo -e "${GREEN}--> Detected NVIDIA GPU hardware!${NC}"
fi
if lspci -nn | grep -Ei "vga|3d|display" | grep -qi "1002:"; then
    HAS_AMD=true
    echo -e "${RED}--> Detected AMD Radeon GPU hardware (Polaris/Vega/RDNA)!${NC}"
fi
if lspci -nn | grep -Ei "vga|3d|display" | grep -qi "8086:"; then
    HAS_INTEL=true
    echo -e "${BLUE}--> Detected Intel GPU hardware!${NC}"
fi

echo -e "${GREEN}[2/6] Installing base tools & multi-vendor driver dependencies...${NC}"
export DEBIAN_FRONTEND=noninteractive
apt-get update -qq
apt-get install -y -qq \
    curl \
    git \
    pciutils \
    lshw \
    python3 \
    python3-venv \
    python3-pip \
    libgomp1 \
    mesa-vulkan-drivers \
    vulkan-tools \
    libvulkan1 \
    xz-utils \
    jq > /dev/null

# Install AMD-specific driver packages if AMD cards present
if [ "$HAS_AMD" = true ] && [ "$IS_HIVEOS" = false ]; then
    echo -e "${YELLOW}--> Installing AMD Vulkan/ROCm driver packages...${NC}"
    apt-get install -y -qq \
        libdrm-amdgpu1 \
        mesa-va-drivers \
        radeontop || true
fi

# Install NVIDIA-specific utilities if NVIDIA cards present
if [ "$HAS_NVIDIA" = true ] && [ "$IS_HIVEOS" = false ]; then
    echo -e "${YELLOW}--> Ensuring NVIDIA utilities & CUDA libraries are available...${NC}"
    apt-get install -y -qq \
        nvidia-utils-535 \
        nvidia-cuda-toolkit || true
fi

echo -e "${GREEN}[3/6] Deploying ComputeMesh Appliance into /opt/computemesh...${NC}"
INSTALL_DIR="/opt/computemesh"
mkdir -p "${INSTALL_DIR}"
mkdir -p "/etc/computemesh"
mkdir -p "/var/log/computemesh"
mkdir -p "/var/lib/computemesh/models"

if [ -d "./tools/appliance" ]; then
    cp -rf ./* "${INSTALL_DIR}/"
else
    if [ ! -d "${INSTALL_DIR}/.git" ]; then
        git clone https://github.com/inetconnector/ComputeMesh.git "${INSTALL_DIR}"
    else
        git -C "${INSTALL_DIR}" pull
    fi
fi

echo -e "${GREEN}[4/6] Creating Python runtime virtual environment...${NC}"
python3 -m venv "${INSTALL_DIR}/.venv"
"${INSTALL_DIR}/.venv/bin/pip" install --upgrade pip -q
if [ -f "${INSTALL_DIR}/requirements.txt" ]; then
    "${INSTALL_DIR}/.venv/bin/pip" install -r "${INSTALL_DIR}/requirements.txt" -q || true
fi

echo -e "${GREEN}[5/6] Scanning native GPU hardware (AMD + NVIDIA) & configuring layer split...${NC}"
"${INSTALL_DIR}/.venv/bin/python" "${INSTALL_DIR}/tools/appliance/hardware_detector.py" \
    --output "/etc/computemesh/inventory.json"

RIG_JSON="/etc/computemesh/inventory.json"
TOTAL_GPUS=$(jq -r '.total_gpus' "$RIG_JSON" 2>/dev/null || echo "0")
TOTAL_VRAM=$(jq -r '.total_vram_bytes' "$RIG_JSON" 2>/dev/null || echo "0")
TOTAL_VRAM_GB=$((TOTAL_VRAM / 1024 / 1024 / 1024))
VENDOR_NV=$(jq -r '.vendor_breakdown.nvidia // 0' "$RIG_JSON" 2>/dev/null || echo "0")
VENDOR_AMD=$(jq -r '.vendor_breakdown.amd // 0' "$RIG_JSON" 2>/dev/null || echo "0")

echo -e "${CYAN}--> Rig Scan Complete: ${TOTAL_GPUS} Total GPUs (${TOTAL_VRAM_GB} GB Aggregate VRAM)${NC}"
echo -e "    • NVIDIA GPUs: ${CYAN}${VENDOR_NV}${NC}"
echo -e "    • AMD GPUs:    ${RED}${VENDOR_AMD}${NC}"

# Auto-Update Preference Prompt (Ed25519 Cryptographic Verification)
ENABLE_AUTO_UPDATE=true
if [ -t 0 ]; then
    read -r -p "Möchtest du automatische kryptografisch signierte Sicherheits- & Leistungsupdates aktivieren? [Y/n]: " update_choice || true
    if [[ "$update_choice" =~ ^[Nn]$ ]]; then
        ENABLE_AUTO_UPDATE=false
    fi
fi

python3 -c "
import json
from pathlib import Path
cfg_file = Path('/etc/computemesh/config.json')
data = {}
if cfg_file.exists():
    try: data = json.loads(cfg_file.read_text(encoding='utf-8'))
    except Exception: pass
data['auto_update'] = ${ENABLE_AUTO_UPDATE}
cfg_file.parent.mkdir(parents=True, exist_ok=True)
cfg_file.write_text(json.dumps(data, indent=2), encoding='utf-8')
" 2>/dev/null || true

echo -e "${GREEN}[6/6] Installing systemd service units...${NC}"

cat << EOF > /etc/systemd/system/computemesh-dashboard.service
[Unit]
Description=ComputeMesh NodeOS Web Dashboard
After=network.target

[Service]
Type=simple
User=root
WorkingDirectory=${INSTALL_DIR}
ExecStart=${INSTALL_DIR}/.venv/bin/python ${INSTALL_DIR}/services/appliance_dashboard/server.py --port 8080
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload
systemctl enable --now computemesh-dashboard.service

PRIMARY_IP=$(hostname -I | awk '{print $1}')

echo ""
echo -e "${GREEN}================================================================${NC}"
echo -e "${GREEN}  ComputeMesh NodeOS (AMD + NVIDIA Native) is Online!           ${NC}"
echo -e "${GREEN}================================================================${NC}"
echo -e "  • Total GPUs Active:  ${CYAN}${TOTAL_GPUS} Cards${NC} (${VENDOR_NV} NVIDIA, ${VENDOR_AMD} AMD)"
echo -e "  • Cluster VRAM:       ${CYAN}${TOTAL_VRAM_GB} GB Total${NC}"
echo -e "  • Local Web Dashboard:${YELLOW} http://${PRIMARY_IP}:8080${NC}"
echo -e "  • Config File:        /etc/computemesh/config.json"
echo -e "${GREEN}================================================================${NC}"
echo ""
