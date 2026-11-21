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
DOWNLOADS_SRC="${REPO_DIR}/portal/downloads"
BACKUP_MODE="${COMPUTEMESH_BACKUP_MODE:-host-managed}"
BACKUP_ROOT="/var/backups/computemesh_portal"
TS="$(date -u +"%Y%m%d_%H%M%S")"
SITE2_BACKUP="${BACKUP_ROOT}/site2_${TS}.tar.gz"
HTTPDOCS_BACKUP="${BACKUP_ROOT}/httpdocs_${TS}.tar.gz"

echo "================================================================="
echo "ComputeMesh Plesk Portal Synchronization (SSOT -> Production)"
echo "Timestamp: $(date -u +"%Y-%m-%dT%H:%M:%SZ")"
echo "================================================================="

# 1. Require explicit, verified release tag (Never deploy untagged main or ambiguous refs)
RELEASE_TAG="${1:-}"
if [ -z "${RELEASE_TAG}" ]; then
  echo "Error: Explicit release tag required as first parameter."
  echo "Usage: $0 <release-tag> (e.g., $0 v1.2.187)"
  echo "Silent fallbacks or unverified HEAD deployments are strictly prohibited."
  exit 1
fi

if [[ ! "${RELEASE_TAG}" =~ ^v[0-9]+\.[0-9]+\.[0-9]+ ]]; then
  echo "Error: Release tag '${RELEASE_TAG}' must follow semantic versioning (vX.Y.Z)."
  exit 1
fi

if [ ! -d "${REPO_DIR}" ]; then
  echo "Error: Repository directory ${REPO_DIR} does not exist."
  exit 1
fi

cd "${REPO_DIR}"
git fetch origin --tags

if ! git rev-parse -q --verify "refs/tags/${RELEASE_TAG}" >/dev/null; then
  echo "Error: Release tag 'refs/tags/${RELEASE_TAG}' does not exist on origin or local tag index."
  echo "Production deployment requires an explicit, annotated release tag."
  exit 1
fi

echo "[1/6] Checking out verified release tag (${RELEASE_TAG})..."
git checkout "refs/tags/${RELEASE_TAG}"

PORTAL_SRC="${REPO_DIR}/portal"
if [ ! -d "${PORTAL_SRC}" ]; then
  echo "Error: Portal source directory ${PORTAL_SRC} not found."
  exit 1
fi

if [ "${BACKUP_MODE}" != "host-managed" ] && [ "${BACKUP_MODE}" != "server" ]; then
  echo "Error: COMPUTEMESH_BACKUP_MODE must be 'host-managed' or 'server'."
  exit 1
fi

if [ ! -d "${DOWNLOADS_SRC}" ]; then
  echo "Error: Immutable release download source ${DOWNLOADS_SRC} not found."
  exit 1
fi

REQUIRED_DOWNLOADS=(
  "ComputeMesh-Setup-x64.exe"
  "computemesh-linux-x86_64.tar.gz"
  "computemesh-nodeos-x86_64.iso"
  "computemesh-nodeos-x86_64.img.xz"
  "computemesh-nodeos-runtime-x86_64.tar.gz"
  "computemesh-nodeos-x86_64.provenance.json"
  "install.sh"
  "ComputeMesh-Android.apk"
  "ComputeMesh-Android.aab"
  "ComputeMesh-Android.json"
  "version.json"
)
for asset in "${REQUIRED_DOWNLOADS[@]}"; do
  if [ ! -s "${DOWNLOADS_SRC}/${asset}" ]; then
    echo "Error: Required immutable release asset missing or empty: ${DOWNLOADS_SRC}/${asset}"
    exit 1
  fi
done

# 2. Select rollback policy before modifying production webroots.
# The default is host-managed: the server/provider backup is authoritative and
# no additional backup archive is left on the live server.
if [ "${BACKUP_MODE}" = "server" ]; then
  mkdir -p "${BACKUP_ROOT}"
else
  echo "Server-local portal backups disabled; relying on host-managed backups."
fi

rollback_and_exit() {
  echo "================================================================="
  echo "CRITICAL: Healthcheck failed! Initiating automatic rollback..."
  echo "================================================================="
  if [ "${BACKUP_MODE}" = "server" ] && [ -f "${SITE2_BACKUP}" ] && [ -d "${SITE2_DIR}" ]; then
    echo "Restoring site2 from ${SITE2_BACKUP}..."
    tar --exclude='downloads' -xzf "${SITE2_BACKUP}" -C "${SITE2_DIR}" || true
  fi
  if [ "${BACKUP_MODE}" = "server" ] && [ -f "${HTTPDOCS_BACKUP}" ] && [ -d "${HTTPDOCS_DIR}" ]; then
    echo "Restoring httpdocs from ${HTTPDOCS_BACKUP}..."
    tar --exclude='downloads' -xzf "${HTTPDOCS_BACKUP}" -C "${HTTPDOCS_DIR}" || true
  fi
  if [ "$EUID" -eq 0 ]; then
    systemctl restart computemesh-gateway.service || true
  fi
  echo "Rollback completed. Exiting with failure status."
  exit 1
}

# 3. Synchronize to site2 (mesh.inetconnector.com)
echo "[2/7] Staging and synchronizing portal assets to site2 (${SITE2_DIR})..."
if [ ! -d "${SITE2_DIR}" ]; then
  echo "Error: ${SITE2_DIR} not found; refusing partial production synchronization."
  exit 1
fi
if [ -d "${SITE2_DIR}" ]; then
  if [ "${BACKUP_MODE}" = "server" ]; then
    echo "Backing up site2 -> ${SITE2_BACKUP}..."
    if ! tar --exclude='downloads' --exclude='.git' -czf "${SITE2_BACKUP}" -C "${SITE2_DIR}" .; then
      echo "Error: Backup of site2 failed! Aborting before modifying production webroot."
      exit 1
    fi
    test -s "${SITE2_BACKUP}" || { echo "Error: site2 backup archive is empty!"; exit 1; }
  fi

  rsync -av \
    --exclude='.git' \
    --exclude='downloads' \
    --exclude='__pycache__' \
    --exclude='*.py' \
    --exclude='__upload_tmp__' \
    "${PORTAL_SRC}/" "${SITE2_DIR}/"

  # Remove legacy root-level Python scripts after successful sync
  rm -f "${SITE2_DIR}"/fleet_accounts.py \
        "${SITE2_DIR}"/passkey_routes.py \
        "${SITE2_DIR}"/mail_dispatcher.py \
        "${SITE2_DIR}"/routes_*.py \
        "${SITE2_DIR}"/server_core.py \
        "${SITE2_DIR}"/server.py \
        "${SITE2_DIR}"/__init__.py
  rm -rf "${SITE2_DIR}"/__pycache__ "${SITE2_DIR}"/tests

  mkdir -p "${SITE2_DIR}/downloads"
  chown "${PLESK_USER}:${PLESK_GROUP}" "${SITE2_DIR}"/* 2>/dev/null || true
fi

# 4. Synchronize to httpdocs (inetconnector.com)
echo "[3/7] Staging and synchronizing portal assets to httpdocs (${HTTPDOCS_DIR})..."
if [ ! -d "${HTTPDOCS_DIR}" ]; then
  echo "Error: ${HTTPDOCS_DIR} not found; refusing partial production synchronization."
  exit 1
fi
if [ -d "${HTTPDOCS_DIR}" ]; then
  if [ "${BACKUP_MODE}" = "server" ]; then
    echo "Backing up httpdocs -> ${HTTPDOCS_BACKUP}..."
    if ! tar --exclude='downloads' --exclude='.git' -czf "${HTTPDOCS_BACKUP}" -C "${HTTPDOCS_DIR}" .; then
      echo "Error: Backup of httpdocs failed! Aborting before modifying production webroot."
      exit 1
    fi
    test -s "${HTTPDOCS_BACKUP}" || { echo "Error: httpdocs backup archive is empty!"; exit 1; }
  fi

  rsync -av \
    --exclude='.git' \
    --exclude='downloads' \
    --exclude='__pycache__' \
    --exclude='*.py' \
    --exclude='__upload_tmp__' \
    "${PORTAL_SRC}/" "${HTTPDOCS_DIR}/"

  rm -f "${HTTPDOCS_DIR}"/fleet_accounts.py \
        "${HTTPDOCS_DIR}"/passkey_routes.py \
        "${HTTPDOCS_DIR}"/mail_dispatcher.py \
        "${HTTPDOCS_DIR}"/routes_*.py \
        "${HTTPDOCS_DIR}"/server_core.py \
        "${HTTPDOCS_DIR}"/server.py \
        "${HTTPDOCS_DIR}"/__init__.py
  rm -rf "${HTTPDOCS_DIR}"/__pycache__ "${HTTPDOCS_DIR}"/tests

  mkdir -p "${HTTPDOCS_DIR}/downloads"
  chown "${PLESK_USER}:${PLESK_GROUP}" "${HTTPDOCS_DIR}"/* 2>/dev/null || true
fi

# 5. Synchronize the complete immutable release asset tree to both webroots.
# The release checkout is the single source of truth; --delete removes stale
# server-only artifacts such as obsolete raw images from the public tree.
echo "[4/7] Synchronizing signed immutable release downloads..."
rsync -av --delete "${DOWNLOADS_SRC}/" "${SITE2_DIR}/downloads/"
rsync -av --delete "${DOWNLOADS_SRC}/" "${HTTPDOCS_DIR}/downloads/"
chown -R "${PLESK_USER}:${PLESK_GROUP}" "${HTTPDOCS_DIR}/downloads" "${SITE2_DIR}/downloads"

# 6. Restart services with strict exit code checking
echo "[5/7] Restarting backend services..."
if [ "$EUID" -eq 0 ]; then
  if ! systemctl restart computemesh-gateway.service; then
    echo "Error: Failed to restart computemesh-gateway.service"
    rollback_and_exit
  fi
  if ! systemctl restart computemesh-autoupdate.service; then
    echo "Warning: Failed to restart computemesh-autoupdate.service"
  fi
  echo "Backend services refreshed successfully."
else
  echo "Notice: Non-root execution. Skipping systemctl reload."
fi

# 7. Local gateway health verification (fail-closed)
echo "[6/7] Verifying local gateway health..."
if command -v curl >/dev/null 2>&1; then
  HEALTH_STATUS="000"
  for retry in {1..15}; do
    HEALTH_STATUS=$(curl -s -o /dev/null -w "%{http_code}" http://127.0.0.1:8000/v1/models || echo "000")
    if [ "${HEALTH_STATUS}" = "200" ]; then
      break
    fi
    sleep 1
  done
  if [ "${HEALTH_STATUS}" != "200" ]; then
    echo "Error: Gateway local healthcheck failed with HTTP ${HEALTH_STATUS}."
    rollback_and_exit
  fi
  echo "Local Gateway Health HTTP Code: ${HEALTH_STATUS} [OK]"
fi

# 8. Public endpoint verification (fail-closed)
echo "[7/7] Verifying public endpoint HTTP status codes..."
if command -v curl >/dev/null 2>&1; then
  for url in \
    "https://mesh.inetconnector.com" \
    "https://inetconnector.com" \
    "https://ai.inetconnector.com"; do
    code=$(curl -s -o /dev/null -w "%{http_code}" -L "$url" || echo "000")
    if [ "$code" != "200" ] && [ "$code" != "301" ] && [ "$code" != "302" ]; then
      echo "Error: Public endpoint ${url} failed with HTTP ${code}."
      rollback_and_exit
    fi
    echo "Endpoint ${url} -> HTTP ${code} [OK]"
  done
fi

echo "================================================================="
echo "Portal Synchronization Complete! Verified Release: ${RELEASE_TAG}"
echo "================================================================="
