#!/usr/bin/env bash
# ==============================================================================
# ComputeMesh Production Deployment & Service Synchronization Script
# Target: mesh.inetconnector.com / /var/www/mesh.inetconnector.com
# ==============================================================================
set -euo pipefail

DEPLOY_DIR="/var/www/mesh.inetconnector.com"
EXPECTED_BRANCH="main"
ANDROID_RELEASE_TAG="android-latest"
ANDROID_RELEASE_BASE="https://github.com/inetconnector/ComputeMesh/releases/download/${ANDROID_RELEASE_TAG}"

echo "================================================================="
echo "Starting ComputeMesh Production Deployment"
echo "Timestamp: $(date -u +"%Y-%m-%dT%H:%M:%SZ")"
echo "================================================================="

if [ ! -d "${DEPLOY_DIR}" ]; then
  echo "Error: Deployment directory ${DEPLOY_DIR} not found."
  exit 1
fi

cd "${DEPLOY_DIR}"

echo "[1/8] Fetching latest commits and tags from origin..."
git fetch origin --tags
git checkout "${EXPECTED_BRANCH}"
git pull --ff-only origin "${EXPECTED_BRANCH}"

echo "[2/8] Synchronizing submodules..."
if [ -f .gitmodules ]; then
  git submodule sync --recursive
  git submodule update --init --recursive
fi

echo "[3/8] Verifying Python dependencies..."
if [ -f requirements.txt ]; then
  python3 -m pip install --quiet --upgrade -r requirements.txt
fi

echo "[4/8] Synchronizing signed Android release assets..."
mkdir -p portal/downloads
ANDROID_TMP="$(mktemp -d)"
trap 'rm -rf "${ANDROID_TMP}"' EXIT

for asset in ComputeMesh-Android.apk ComputeMesh-Android.aab ComputeMesh-Android.json; do
  echo "Downloading ${asset} from ${ANDROID_RELEASE_TAG}..."
  curl --fail --location --silent --show-error \
    "${ANDROID_RELEASE_BASE}/${asset}" \
    --output "${ANDROID_TMP}/${asset}"
  test -s "${ANDROID_TMP}/${asset}"
done

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

url = str(meta.get("url", ""))
if url != "https://mesh.inetconnector.com/downloads/ComputeMesh-Android.apk":
    raise SystemExit(f"Unexpected Android public URL in metadata: {url}")
print(f"Android release {meta.get('version', meta.get('version_name', 'unknown'))} verified")
PY

if command -v unzip >/dev/null 2>&1; then
  unzip -tq "${ANDROID_TMP}/ComputeMesh-Android.apk" >/dev/null
  unzip -tq "${ANDROID_TMP}/ComputeMesh-Android.aab" >/dev/null
fi

install -m 0644 "${ANDROID_TMP}/ComputeMesh-Android.apk" portal/downloads/ComputeMesh-Android.apk
install -m 0644 "${ANDROID_TMP}/ComputeMesh-Android.aab" portal/downloads/ComputeMesh-Android.aab
install -m 0644 "${ANDROID_TMP}/ComputeMesh-Android.json" portal/downloads/ComputeMesh-Android.json
rm -f portal/downloads/ComputeMesh-Android.apk.idsig

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
  systemctl restart compumesh-portal.service
  systemctl restart compumesh-gateway.service
  systemctl enable --now compumesh-retention.timer
  echo "Services restarted and retention timer active."
else
  echo "Notice: Non-root execution. Skipping systemd service restart."
fi

echo "[7/8] Executing local health check..."
if command -v curl >/dev/null 2>&1; then
  HEALTH_STATUS=$(curl -s -o /dev/null -w "%{http_code}" http://127.0.0.1:8000/status || true)
  if [ "${HEALTH_STATUS}" != "200" ]; then
    echo "Error: Portal health check failed with HTTP ${HEALTH_STATUS:-000}."
    exit 1
  fi
  echo "Portal status HTTP code: ${HEALTH_STATUS}"
fi

echo "[8/8] Verifying public Android download endpoints..."
if command -v curl >/dev/null 2>&1; then
  for url in \
    "https://mesh.inetconnector.com/downloads/ComputeMesh-Android.apk" \
    "https://mesh.inetconnector.com/downloads/ComputeMesh-Android.aab" \
    "https://mesh.inetconnector.com/downloads/ComputeMesh-Android.json"; do
    code=$(curl --location --silent --show-error --output /dev/null --write-out "%{http_code}" "$url" || true)
    if [ "$code" != "200" ]; then
      echo "Error: Public download verification failed for ${url} (HTTP ${code:-000})."
      exit 1
    fi
    echo "Verified ${url} -> HTTP 200"
  done
fi

echo "================================================================="
echo "ComputeMesh Deployment Completed Successfully!"
echo "================================================================="
