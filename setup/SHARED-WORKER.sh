#!/usr/bin/env bash
set -Eeuo pipefail
SETUP_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SETUP_DIR/linux.sh"
MODE=shared-worker
heading
printf '%s\n' 'ComputeMesh M1 shared worker'
printf '%s\n' 'Trusted private LAN only. Never expose llama.cpp RPC to the public internet.'
py="$(ensure_python)"
status="$(invoke_lab status | tail -n1)"
saved_bench="$(json_field "$status" llama_bench)"

find_rpc_server() {
  local runtime found
  if [[ -n "$saved_bench" && -f "$saved_bench" ]]; then
    for name in rpc-server ggml-rpc-server; do
      found="$(find "$(dirname "$saved_bench")" -type f -name "$name" -print -quit 2>/dev/null || true)"
      [[ -n "$found" ]] && { printf '%s\n' "$found"; return 0; }
    done
    return 0
  fi
  runtime="$REPO_ROOT/artifacts/lab/runtime/llama.cpp"
  if [[ -d "$runtime" ]]; then
    for name in rpc-server ggml-rpc-server; do
      found="$(find "$runtime" -type f -name "$name" -print -quit 2>/dev/null || true)"
      [[ -n "$found" ]] && { printf '%s\n' "$found"; return 0; }
    done
  fi
  command -v rpc-server 2>/dev/null || command -v ggml-rpc-server 2>/dev/null || true
}

rpc="$(find_rpc_server)"
if [[ -n "$saved_bench" && -f "$saved_bench" && -z "$rpc" ]]; then
  echo 'No rpc-server was found in the same llama.cpp build tree as the remembered llama-bench. Install/use a complete matching build and rerun llama-bench; cross-build fallback is disabled for the shared proof.' >&2
  exit 1
fi
if [[ -z "$rpc" ]]; then
  read -r -e -p 'rpc-server / ggml-rpc-server path: ' rpc
  rpc="${rpc%\"}"; rpc="${rpc#\"}"
fi
[[ -f "$rpc" ]] || { echo 'RPC server executable not found.' >&2; exit 1; }
chmod +x "$rpc" 2>/dev/null || true
info="$(private_lan_info)" || { echo 'No RFC1918 LAN interface found.' >&2; exit 1; }
IFS='|' read -r ip dev network <<<"$info"
port=50052
threads=1
if command -v nproc >/dev/null 2>&1; then threads="$(nproc)"; fi
[[ "$threads" =~ ^[0-9]+$ ]] || threads=1
(( threads > 0 )) || threads=1

fw_kind=''; fw_zone=''; fw_rule=''
cleanup_rpc_firewall() {
  set +e
  case "$fw_kind" in
    firewalld) as_root firewall-cmd --zone="$fw_zone" --remove-rich-rule="$fw_rule" >/dev/null 2>&1 ;;
    ufw) as_root ufw --force delete allow from "$network" to "$ip" port "$port" proto tcp >/dev/null 2>&1 ;;
  esac
  fw_kind=''
  set -e
}
if command -v firewall-cmd >/dev/null 2>&1 && systemctl is-active --quiet firewalld 2>/dev/null; then
  fw_zone="$(firewall-cmd --get-zone-of-interface="$dev" 2>/dev/null || true)"; [[ -n "$fw_zone" ]] || fw_zone=public
  fw_rule="rule family=ipv4 source address=$network destination address=$ip port port=$port protocol=tcp accept"
  as_root firewall-cmd --zone="$fw_zone" --add-rich-rule="$fw_rule" >/dev/null
  fw_kind=firewalld
elif command -v ufw >/dev/null 2>&1 && as_root ufw status 2>/dev/null | grep -q '^Status: active'; then
  as_root ufw allow from "$network" to "$ip" port "$port" proto tcp >/dev/null
  fw_kind=ufw
fi
trap cleanup_rpc_firewall EXIT INT TERM
rpc_dir="$(dirname "$rpc")"
export LD_LIBRARY_PATH="$rpc_dir:$(dirname "$rpc_dir"):$rpc_dir/lib:${LD_LIBRARY_PATH:-}"
printf '\nWorker RPC endpoint: %s:%s\nCPU threads if CPU fallback is used: %s\n' "$ip" "$port" "$threads"
echo 'Keep this window open while the coordinator runs SHARED-PROOF. Ctrl+C stops the worker.'
(cd "$REPO_ROOT" && "$py" -m runtime.llama.rpc_spike worker --rpc-server "$rpc" --bind "$ip" --port "$port" --threads "$threads")
