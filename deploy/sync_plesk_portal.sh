#!/usr/bin/env bash
# ==============================================================================
# ComputeMesh Plesk Portal Synchronization & SSOT Deployment Script
# Targets:
#   - mesh.inetconnector.com        (/var/www/vhosts/inetconnector.com/site2)
#   - computemesh.inetconnector.com (/var/www/vhosts/inetconnector.com/site2)
#   - inetconnector.com             (/var/www/vhosts/inetconnector.com/httpdocs)
# ==============================================================================
set -euo pipefail

REPO_DIR="/opt/computemesh"
SITE2_DIR="/var/www/vhosts/inetconnector.com/site2"
HTTPDOCS_DIR="/var/www/vhosts/inetconnector.com/httpdocs"
PLESK_USER="inetconnector"
PLESK_GROUP="psacln"

echo "================================================================="
echo "ComputeMesh Plesk Portal Synchronization (SSOT -> Production)"
echo "Timestamp: $(date -u +"%Y-%m-%dT%H:%M:%SZ")"
echo "================================================================="

# 1. Verify and update Git repository
if [ ! -d "${REPO_DIR}" ]; then
  echo "Error: Repository directory ${REPO_DIR} does not exist."
  exit 1
fi

cd "${REPO_DIR}"
echo "[1/6] Fetching and pulling latest changes from GitHub (origin/main)..."
git fetch origin main
git checkout main
git pull --ff-only origin main

PORTAL_SRC="${REPO_DIR}/portal"
if [ ! -d "${PORTAL_SRC}" ]; then
  echo "Error: Portal source directory ${PORTAL_SRC} not found."
  exit 1
fi

# 2. Synchronize to site2 (mesh.inetconnector.com)
echo "[2/6] Synchronizing portal assets to site2 (${SITE2_DIR})..."
if [ -d "${SITE2_DIR}" ]; then
  # Remove legacy root-level Python scripts if present
  rm -f "${SITE2_DIR}"/fleet_accounts.py \
        "${SITE2_DIR}"/passkey_routes.py \
        "${SITE2_DIR}"/mail_dispatcher.py \
        "${SITE2_DIR}"/routes_*.py \
        "${SITE2_DIR}"/server_core.py \
        "${SITE2_DIR}"/server.py \
        "${SITE2_DIR}"/__init__.py
  rm -rf "${SITE2_DIR}"/__pycache__ "${SITE2_DIR}"/tests

  rsync -av \
    --exclude='downloads' \
    --exclude='.git' \
    --exclude='__pycache__' \
    --exclude='*.py' \
    --exclude='__upload_tmp__' \
    "${PORTAL_SRC}/" "${SITE2_DIR}/"
  
  # Ensure downloads directory exists
  mkdir -p "${SITE2_DIR}/downloads"
  chown -R "${PLESK_USER}:${PLESK_GROUP}" "${SITE2_DIR}"
else
  echo "Warning: ${SITE2_DIR} not found, skipping."
fi

# 3. Synchronize to httpdocs (inetconnector.com)
echo "[3/6] Synchronizing portal assets to httpdocs (${HTTPDOCS_DIR})..."
if [ -d "${HTTPDOCS_DIR}" ]; then
  # Remove legacy root-level Python scripts if present
  rm -f "${HTTPDOCS_DIR}"/fleet_accounts.py \
        "${HTTPDOCS_DIR}"/passkey_routes.py \
        "${HTTPDOCS_DIR}"/mail_dispatcher.py \
        "${HTTPDOCS_DIR}"/routes_*.py \
        "${HTTPDOCS_DIR}"/server_core.py \
        "${HTTPDOCS_DIR}"/server.py \
        "${HTTPDOCS_DIR}"/__init__.py
  rm -rf "${HTTPDOCS_DIR}"/__pycache__ "${HTTPDOCS_DIR}"/tests

  rsync -av \
    --exclude='downloads' \
    --exclude='.git' \
    --exclude='__pycache__' \
    --exclude='*.py' \
    --exclude='__upload_tmp__' \
    "${PORTAL_SRC}/" "${HTTPDOCS_DIR}/"

  # Ensure downloads directory exists
  mkdir -p "${HTTPDOCS_DIR}/downloads"
  chown -R "${PLESK_USER}:${PLESK_GROUP}" "${HTTPDOCS_DIR}"
else
  echo "Warning: ${HTTPDOCS_DIR} not found, skipping."
fi

# 4. Restart services if running as root
echo "[4/6] Restarting backend services..."
if [ "$EUID" -eq 0 ]; then
  systemctl restart computemesh-gateway.service || true
  systemctl restart computemesh-autoupdate.service || true
  echo "Backend services refreshed."
else
  echo "Notice: Non-root execution. Skipping systemctl reload."
fi

# 5. Local gateway health verification
echo "[5/6] Verifying local gateway health..."
if command -v curl >/dev/null 2>&1; then
  HEALTH_STATUS=$(curl -s -o /dev/null -w "%{http_code}" http://127.0.0.1:8000/status || curl -s -o /dev/null -w "%{http_code}" http://127.0.0.1:8000/v1/models || true)
  echo "Local Gateway Health HTTP Code: ${HEALTH_STATUS:-unknown}"
fi

# 6. Public endpoint verification
echo "[6/6] Verifying public endpoint HTTP status codes..."
if command -v curl >/dev/null 2>&1; then
  for url in \
    "https://mesh.inetconnector.com" \
    "https://inetconnector.com" \
    "https://ai.inetconnector.com"; do
    code=$(curl -s -o /dev/null -w "%{http_code}" -L "$url" || true)
    echo "Endpoint ${url} -> HTTP ${code}"
  done
fi

echo "================================================================="
echo "Portal Synchronization Complete! GitHub is the active SSOT."
echo "================================================================="
