#!/usr/bin/env bash
# ==============================================================================
# ComputeMesh Production Deployment & Service Synchronization Script
# Target: mesh.inetconnector.com / /var/www/mesh.inetconnector.com
# ==============================================================================
set -euo pipefail

DEPLOY_DIR="/var/www/mesh.inetconnector.com"
BACKUP_ROOT="/var/backups/computemesh_deploy"
TS="$(date -u +"%Y%m%d_%H%M%S")"
DEPLOY_BACKUP="${BACKUP_ROOT}/mesh_deploy_${TS}.tar.gz"

echo "================================================================="
echo "Starting ComputeMesh Production Deployment"
echo "Timestamp: $(date -u +"%Y-%m-%dT%H:%M:%SZ")"
echo "================================================================="

# 1. Require explicit, verified release tag (no mutable pointers or untagged main)
RELEASE_TAG="${1:-}"
if [ -z "${RELEASE_TAG}" ]; then
  echo "Error: Explicit release tag required as first parameter."
  echo "Usage: $0 <release-tag> (e.g., $0 v1.2.187)"
  echo "Deploying unreviewed branches or mutable 'latest' tags is strictly forbidden."
  exit 1
fi

if [[ ! "${RELEASE_TAG}" =~ ^v[0-9]+\.[0-9]+\.[0-9]+ ]]; then
  echo "Error: Release tag '${RELEASE_TAG}' must follow semantic versioning (vX.Y.Z)."
  exit 1
fi

ANDROID_RELEASE_TAG="${2:-$RELEASE_TAG}"
ANDROID_RELEASE_BASE="https://github.com/inetconnector/ComputeMesh/releases/download/${ANDROID_RELEASE_TAG}"

if [ ! -d "${DEPLOY_DIR}" ]; then
  echo "Error: Deployment directory ${DEPLOY_DIR} not found."
  exit 1
fi

cd "${DEPLOY_DIR}"

mkdir -p "${BACKUP_ROOT}"
rollback_deploy_and_exit() {
  echo "================================================================="
  echo "CRITICAL: Deployment healthcheck failed! Initiating rollback..."
  echo "================================================================="
  if [ -f "${DEPLOY_BACKUP}" ]; then
    echo "Restoring deployment directory from ${DEPLOY_BACKUP}..."
    tar --exclude='portal/downloads' --exclude='data' --exclude='.git' -xzf "${DEPLOY_BACKUP}" -C "${DEPLOY_DIR}" || true
  fi
  if [ "$EUID" -eq 0 ]; then
    systemctl restart compumesh-portal.service || true
    systemctl restart compumesh-gateway.service || true
  fi
  echo "Rollback complete. Exiting with failure."
  exit 1
}

echo "[1/8] Fetching release tag ${RELEASE_TAG} from origin..."
git fetch origin --tags
if ! git rev-parse -q --verify "refs/tags/${RELEASE_TAG}" >/dev/null; then
  echo "Error: Release tag 'refs/tags/${RELEASE_TAG}' does not exist on origin or local tag index."
  echo "Production deployment requires an explicit, annotated release tag."
  exit 1
fi

echo "Creating rollback snapshot before modifying deployment tree..."
if ! tar --exclude='portal/downloads' --exclude='data' --exclude='.git' -czf "${DEPLOY_BACKUP}" -C "${DEPLOY_DIR}" .; then
  echo "Error: Deployment directory backup failed! Aborting before modifying files."
  exit 1
fi
test -s "${DEPLOY_BACKUP}" || { echo "Error: Backup archive is empty!"; exit 1; }

echo "Checking out verified release tag (${RELEASE_TAG})..."
git checkout "refs/tags/${RELEASE_TAG}"

echo "[2/8] Synchronizing submodules..."
if [ -f .gitmodules ]; then
  git submodule sync --recursive
  git submodule update --init --recursive
fi

echo "[3/8] Verifying Python dependencies..."
if [ -f requirements.txt ]; then
  python3 -m pip install --quiet --upgrade -r requirements.txt
fi

echo "[4/8] Synchronizing signed Android release assets (${ANDROID_RELEASE_TAG})..."
mkdir -p portal/downloads
ANDROID_TMP="$(mktemp -d)"
trap 'rm -rf "${ANDROID_TMP}"' EXIT

for asset in ComputeMesh-Android.apk ComputeMesh-Android.aab ComputeMesh-Android.json; do
  echo "Downloading ${asset} from ${ANDROID_RELEASE_TAG}..."
  if ! curl --fail --location --silent --show-error \
    "${ANDROID_RELEASE_BASE}/${asset}" \
    --output "${ANDROID_TMP}/${asset}"; then
    echo "Warning: Could not fetch Android asset ${asset} from ${ANDROID_RELEASE_BASE}. Retaining existing downloads."
    break
  fi
  test -s "${ANDROID_TMP}/${asset}"
done

if [ -s "${ANDROID_TMP}/ComputeMesh-Android.json" ] && [ -s "${ANDROID_TMP}/ComputeMesh-Android.apk" ]; then
  python3 - "${ANDROID_TMP}" <<'PY'
import hashlib
import json
import pathlib
import sys

dir_path = pathlib.Path(sys.argv[1])
meta = json.loads((dir_path / "ComputeMesh-Android.json").read_text(encoding="utf-8"))

for filename, field in (
    ("ComputeMesh-Android.apk", "apk_sha256"),
    ("ComputeMesh-Android.aab", "aab_sha256"),
):
    path = dir_path / filename
    if not path.exists():
        continue
    expected = str(meta.get(field) or (meta.get("sha256") if filename.endswith(".apk") else "")).lower().strip()
    if len(expected) != 64:
        raise SystemExit(f"Missing/invalid {field} in Android release metadata")
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(chunk)
    actual = h.hexdigest()
    if actual != expected:
        raise SystemExit(f"SHA-256 mismatch for {filename}: expected {expected}, got {actual}")

print(f"Android release {meta.get('version', meta.get('version_name', 'unknown'))} verified")
PY

  if command -v unzip >/dev/null 2>&1; then
    unzip -tq "${ANDROID_TMP}/ComputeMesh-Android.apk" >/dev/null
    if [ -f "${ANDROID_TMP}/ComputeMesh-Android.aab" ]; then
      unzip -tq "${ANDROID_TMP}/ComputeMesh-Android.aab" >/dev/null
    fi
  fi

  install -m 0644 "${ANDROID_TMP}/ComputeMesh-Android.apk" portal/downloads/ComputeMesh-Android.apk
  if [ -f "${ANDROID_TMP}/ComputeMesh-Android.aab" ]; then
    install -m 0644 "${ANDROID_TMP}/ComputeMesh-Android.aab" portal/downloads/ComputeMesh-Android.aab
  fi
  install -m 0644 "${ANDROID_TMP}/ComputeMesh-Android.json" portal/downloads/ComputeMesh-Android.json
  rm -f portal/downloads/ComputeMesh-Android.apk.idsig
fi

echo "[5/8] Executing database schema migrations (Schema v2)..."
python3 -c "
from services.compliance.provider_identity_store import ProviderIdentityStore
store = ProviderIdentityStore('data/provider_identity.db')
print('ProviderIdentityStore Schema v2 verified successfully.')
"

echo "[6/8] Updating systemd unit files & restarting services..."
if [ -d "/etc/systemd/system" ] && [ "$EUID" -eq 0 ]; then
  cp deploy/systemd/compumesh-*.service /etc/systemd/system/
  cp deploy/systemd/compumesh-*.timer /etc/systemd/system/
  systemctl daemon-reload
  if ! systemctl restart compumesh-portal.service; then
    echo "Error: Failed to restart compumesh-portal.service"
    rollback_deploy_and_exit
  fi
  if ! systemctl restart compumesh-gateway.service; then
    echo "Error: Failed to restart compumesh-gateway.service"
    rollback_deploy_and_exit
  fi
  systemctl enable --now compumesh-retention.timer || true
  echo "Services restarted and retention timer active."
else
  echo "Notice: Non-root execution. Skipping systemd service restart."
fi

echo "[7/8] Executing local health check (fail-closed)..."
if command -v curl >/dev/null 2>&1; then
  HEALTH_STATUS=$(curl -s -o /dev/null -w "%{http_code}" http://127.0.0.1:8000/status || echo "000")
  if [ "${HEALTH_STATUS}" != "200" ]; then
    echo "Error: Portal health check failed with HTTP ${HEALTH_STATUS:-000}."
    rollback_deploy_and_exit
  fi
  echo "Portal status HTTP code: ${HEALTH_STATUS} [OK]"
fi

echo "[8/8] Verifying public download endpoints..."
if command -v curl >/dev/null 2>&1; then
  for url in \
    "https://mesh.inetconnector.com/downloads/ComputeMesh-Setup-x64.exe" \
    "https://mesh.inetconnector.com/downloads/computemesh-linux-x86_64.tar.gz" \
    "https://mesh.inetconnector.com/downloads/install.sh"; do
    code=$(curl --location --silent --show-error --output /dev/null --write-out "%{http_code}" "$url" || echo "000")
    if [ "$code" != "200" ]; then
      echo "Error: Public download verification failed for ${url} (HTTP ${code:-000})."
      rollback_deploy_and_exit
    fi
    echo "Verified ${url} -> HTTP 200 [OK]"
  done
fi

echo "================================================================="
echo "ComputeMesh Deployment Completed Successfully! Release: ${RELEASE_TAG}"
echo "================================================================="
