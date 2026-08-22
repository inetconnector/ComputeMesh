#!/usr/bin/env bash
set -Eeuo pipefail
SETUP_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SETUP_DIR/linux.sh"
MODE=shared-proof
heading
printf '%s\n' 'ComputeMesh M1 shared proof - coordinator'
printf '%s\n' 'Trusted private LAN only. The upstream llama.cpp RPC socket is not authenticated.'
py="$(ensure_python)"
if ! "$py" -c 'import jsonschema' >/dev/null 2>&1; then
  echo 'Installing the small JSON-schema dependency into .venv...'
  "$py" -m pip install 'jsonschema>=4.23,<5'
fi

find_runtime_binary() {
  local name="$1" saved="${2:-}" runtime found
  if [[ -n "$saved" && -e "$saved" ]]; then
    found="$(find "$(dirname "$saved")" -type f -name "$name" -print -quit 2>/dev/null || true)"
    [[ -n "$found" ]] && { printf '%s\n' "$found"; return 0; }
  fi
  runtime="$REPO_ROOT/artifacts/lab/runtime/llama.cpp"
  if [[ -d "$runtime" ]]; then
    found="$(find "$runtime" -type f -name "$name" -print -quit 2>/dev/null || true)"
    [[ -n "$found" ]] && { printf '%s\n' "$found"; return 0; }
  fi
  command -v "$name" 2>/dev/null || true
}

read -r -e -p 'Current experiment_bundle.json: ' bundle
bundle="${bundle%\"}"; bundle="${bundle#\"}"
[[ -f "$bundle" ]] || { echo 'Experiment bundle not found.' >&2; exit 1; }
model="$(choose_model)"
status="$(invoke_lab status | tail -n1)"
saved_bench="$(json_field "$status" llama_bench)"
server="$(find_runtime_binary llama-server "$saved_bench")"
if [[ -z "$server" ]]; then
  read -r -e -p 'llama-server path: ' server
  server="${server%\"}"; server="${server#\"}"
fi
[[ -f "$server" ]] || { echo 'llama-server not found.' >&2; exit 1; }
chmod +x "$server" 2>/dev/null || true
cli="$(find_runtime_binary llama-cli "$server")"
[[ -n "$cli" ]] && chmod +x "$cli" 2>/dev/null || true

worker_ip=''
while ! is_private_ipv4 "$worker_ip"; do
  read -r -p 'Worker private IPv4: ' worker_ip
  is_private_ipv4 "$worker_ip" || echo 'Enter an RFC1918 private IPv4 address.' >&2
done
worker="$worker_ip:50052"
node_id="$(json_field "$status" node_id)"
stamp="$(date -u +%Y%m%d-%H%M%SZ)"
output="$REPO_ROOT/artifacts/lab/$node_id/${stamp}-shared-proof"
server_dir="$(dirname "$server")"
export LD_LIBRARY_PATH="$server_dir:$(dirname "$server_dir"):$server_dir/lib:${LD_LIBRARY_PATH:-}"
args=(-m runtime.llama.shared_trial --bundle "$bundle" --llama-server "$server" --model "$model" --worker-rpc "$worker" --output-dir "$output")
[[ -n "$cli" && -f "$cli" ]] && args+=(--llama-cli "$cli")
set +e
(cd "$REPO_ROOT" && "$py" "${args[@]}")
rc=$?
set -e
if [[ $rc -ne 0 ]]; then
  echo "Trial artifacts/failure record: $output" >&2
  exit "$rc"
fi
printf '\nShared proof: %s\nComparison: %s\n' "$output/shared_run_evidence.json" "$output/comparison.json"
