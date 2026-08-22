#!/usr/bin/env bash
set -Eeuo pipefail
SETUP_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# Reuse the existing setup bootstrap/venv helpers without running its main().
source "$SETUP_DIR/linux.sh"
MODE=bundle
heading
py="$(ensure_python)"
if ! "$py" -c 'import jsonschema' >/dev/null 2>&1; then
  echo 'Installing the small JSON-schema dependency into .venv...'
  "$py" -m pip install 'jsonschema>=4.23,<5'
fi
read -r -e -p 'Peer evidence export ZIP: ' peer_export
peer_export="${peer_export%\"}"; peer_export="${peer_export#\"}"
[[ -f "$peer_export" ]] || { echo 'Peer export ZIP not found.' >&2; exit 1; }
read -r -e -p 'ComputeMesh model manifest JSON: ' model_manifest
model_manifest="${model_manifest%\"}"; model_manifest="${model_manifest#\"}"
[[ -f "$model_manifest" ]] || { echo 'Model manifest not found.' >&2; exit 1; }
invoke_lab bundle --peer-export "$peer_export" --model-manifest "$model_manifest"
