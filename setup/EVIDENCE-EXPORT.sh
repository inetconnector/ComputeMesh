#!/usr/bin/env bash
set -Eeuo pipefail
SETUP_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# Reuse the existing setup bootstrap/venv helpers without running its main().
source "$SETUP_DIR/linux.sh"
MODE=export
heading
invoke_lab export
