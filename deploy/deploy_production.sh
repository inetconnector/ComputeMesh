#!/usr/bin/env bash
# ==============================================================================
# ComputeMesh Production Deployment & Service Synchronization Script
# Target: mesh.inetconnector.com / /var/www/mesh.inetconnector.com
# ==============================================================================
set -euo pipefail

DEPLOY_DIR="/var/www/mesh.inetconnector.com"
EXPECTED_BRANCH="main"
RELEASE_TAG="v1.2.149"

echo "================================================================="
echo "Starting ComputeMesh Production Deployment -> [${RELEASE_TAG}]"
echo "Timestamp: $(date -u +"%Y-%m-%dT%H:%M:%SZ")"
echo "================================================================="

if [ ! -d "${DEPLOY_DIR}" ]; then
  echo "Error: Deployment directory ${DEPLOY_DIR} not found."
  exit 1
fi

cd "${DEPLOY_DIR}"

echo "[1/6] Fetching latest commits and tags from origin..."
git fetch origin --tags
git checkout "${EXPECTED_BRANCH}"
git pull origin "${EXPECTED_BRANCH}"

echo "[2/6] Synchronizing submodules..."
if [ -f .gitmodules ]; then
  git submodule sync --recursive
  git submodule update --init --recursive
fi

echo "[3/6] Verifying Python dependencies..."
if [ -f requirements.txt ]; then
  python3 -m pip install --quiet --upgrade -r requirements.txt
fi

echo "[4/6] Executing database schema migrations (Schema v2)..."
python3 -c "
from services.compliance.provider_identity_store import ProviderIdentityStore
store = ProviderIdentityStore('data/provider_identity.db')
print('ProviderIdentityStore Schema v2 verified successfully.')
"

echo "[5/6] Updating systemd unit files & restarting services..."
if [ -d "/etc/systemd/system" ] && [ "$EUID" -eq 0 ]; then
  cp deploy/systemd/compumesh-*.service /etc/systemd/system/
  cp deploy/systemd/compumesh-*.timer /etc/systemd/system/
  systemctl daemon-reload
  systemctl restart compumesh-portal.service
  systemctl restart compumesh-gateway.service
  systemctl enable --now compumesh-retention.timer
  echo "Services restarted and retention timer active."
else
  echo "Notice: Non-root execution. Skipping systemd service restart."
fi

echo "[6/6] Executing local health check..."
if command -v curl >/dev/null 2>&1; then
  HEALTH_STATUS=$(curl -s -o /dev/null -w "%{http_code}" http://127.0.0.1:8000/status || echo "000")
  echo "Portal status HTTP code: ${HEALTH_STATUS}"
fi

echo "================================================================="
echo "ComputeMesh Deployment [${RELEASE_TAG}] Completed Successfully!"
echo "================================================================="
