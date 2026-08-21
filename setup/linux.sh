#!/usr/bin/env bash
set -Eeuo pipefail

SETUP_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SETUP_DIR/.." && pwd)"
VENV_DIR="$REPO_ROOT/.venv"
VENV_PY="$VENV_DIR/bin/python"
LAB_HELPER="$SETUP_DIR/lab.py"
DEFAULT_PORT=43191
MODE="${1:-menu}"
LANGUAGE="${COMPUTEMESH_LANG:-auto}"
FW_KIND=""
FW_ZONE=""
FW_RULE=""
FW_NETWORK=""
FW_IP=""

if [[ "$LANGUAGE" == auto ]]; then
  case "${LC_ALL:-${LC_MESSAGES:-${LANG:-en}}}" in de*|de_DE*) LANGUAGE=de ;; *) LANGUAGE=en ;; esac
fi
[[ "$LANGUAGE" == de ]] || LANGUAGE=en

text() {
  local key="$1"
  if [[ "$LANGUAGE" == de ]]; then
    case "$key" in
      title) echo 'ComputeMesh Lab Setup' ;;
      menu) echo 'Was möchtest du tun?' ;;
      node) echo 'Diesen Rechner vorbereiten und Profil erstellen' ;;
      server) echo 'Netzwerktest: dieser Rechner wartet (Server / Node B)' ;;
      client) echo 'Netzwerktest: Verbindung zum anderen Rechner messen (Client / Node A)' ;;
      llama) echo 'llama.cpp Prefill/Decode messen' ;;
      tests) echo 'Alle lokalen Tests ausführen' ;;
      exit) echo 'Beenden' ;;
      choice) echo 'Auswahl' ;;
      install) echo 'Benötigte Linux-Pakete fehlen. Jetzt installieren?' ;;
      private) echo 'Nur in einem vertrauenswürdigen privaten LAN ausführen.' ;;
      ip) echo 'IP dieses Rechners' ;;
      server_help) echo 'Auf dem anderen Rechner ./setup.sh starten, Client wählen und diese IP eingeben.' ;;
      enter_ip) echo 'IP des Server-Rechners' ;;
      bad_ip) echo 'Bitte private LAN-IP eingeben (10.x, 172.16-31.x oder 192.168.x).' ;;
      auto_llama) echo 'Offizielles llama.cpp-Linux-Paket automatisch herunterladen' ;;
      existing_llama) echo 'Vorhandenes llama-bench verwenden' ;;
      model) echo 'Pfad zur GGUF-Modelldatei' ;;
      done) echo 'Fertig.' ;;
      results) echo 'Ergebnisse' ;;
      press) echo 'Enter drücken zum Fortfahren' ;;
      no_python) echo 'Python 3.10+ konnte nicht eingerichtet werden.' ;;
      unsupported_pm) echo 'Kein unterstützter Paketmanager gefunden. Bitte Python 3.10+, venv, curl, tar und iproute2 installieren.' ;;
      firewall) echo 'Eine aktive ufw/firewalld-Regel wird nur für dieses private Subnetz temporär geöffnet und danach entfernt.' ;;
      download) echo 'Neueste offizielle llama.cpp-Linux-Version wird geladen...' ;;
      no_asset) echo 'Kein passendes offizielles Linux-llama.cpp-Paket gefunden.' ;;
      ubuntu_note) echo 'Der automatische llama.cpp-Download verwendet offizielle Ubuntu-Binaries; auf anderen glibc-Distributionen wird die Binary nach dem Entpacken geprüft.' ;;
      *) echo "$key" ;;
    esac
  else
    case "$key" in
      title) echo 'ComputeMesh Lab Setup' ;;
      menu) echo 'What do you want to do?' ;;
      node) echo 'Prepare this computer and capture its profile' ;;
      server) echo 'Network test: wait here (Server / Node B)' ;;
      client) echo 'Network test: measure the other computer (Client / Node A)' ;;
      llama) echo 'Measure llama.cpp prefill/decode' ;;
      tests) echo 'Run all local tests' ;;
      exit) echo 'Exit' ;;
      choice) echo 'Choice' ;;
      install) echo 'Required Linux packages are missing. Install them now?' ;;
      private) echo 'Run only on a trusted private LAN.' ;;
      ip) echo 'This computer IP' ;;
      server_help) echo 'On the other computer run ./setup.sh, choose Client, and enter this IP.' ;;
      enter_ip) echo 'Server computer IP' ;;
      bad_ip) echo 'Enter a private LAN IP (10.x, 172.16-31.x, or 192.168.x).' ;;
      auto_llama) echo 'Download official llama.cpp Linux package automatically' ;;
      existing_llama) echo 'Use an existing llama-bench' ;;
      model) echo 'Path to GGUF model file' ;;
      done) echo 'Done.' ;;
      results) echo 'Results' ;;
      press) echo 'Press Enter to continue' ;;
      no_python) echo 'Python 3.10+ could not be configured.' ;;
      unsupported_pm) echo 'No supported package manager found. Install Python 3.10+, venv, curl, tar, and iproute2.' ;;
      firewall) echo 'An active ufw/firewalld rule is opened only for this private subnet and removed after the one-shot test.' ;;
      download) echo 'Downloading the latest official llama.cpp Linux release...' ;;
      no_asset) echo 'No suitable official Linux llama.cpp package was found.' ;;
      ubuntu_note) echo 'Automatic llama.cpp download uses official Ubuntu binaries; on other glibc distributions the extracted binary is verified before use.' ;;
      *) echo "$key" ;;
    esac
  fi
}

heading() { printf '\033[2J\033[H'; printf '%s\n  %s\n%s\n\n' '================================================================' "$(text title)" '================================================================'; }
pause_ui() { [[ "$MODE" == menu ]] && read -r -p "$(text press)" _ || true; }

python_ok() {
  local exe="$1"
  "$exe" -c 'import sys; raise SystemExit(0 if sys.version_info >= (3,10) else 1)' >/dev/null 2>&1
}

find_python() {
  local exe
  for exe in python3 python; do
    if command -v "$exe" >/dev/null 2>&1 && python_ok "$(command -v "$exe")"; then command -v "$exe"; return 0; fi
  done
  return 1
}

as_root() {
  if [[ ${EUID:-$(id -u)} -eq 0 ]]; then "$@"; elif command -v sudo >/dev/null 2>&1; then sudo "$@"; else return 126; fi
}

package_manager() {
  local x
  for x in apt-get dnf zypper pacman apk; do command -v "$x" >/dev/null 2>&1 && { echo "$x"; return 0; }; done
  return 1
}

install_linux_packages() {
  local pm="${1:-}" response
  [[ -n "$pm" ]] || pm="$(package_manager || true)"
  [[ -n "$pm" ]] || { echo "$(text unsupported_pm)" >&2; return 1; }
  read -r -p "$(text install) [Y/n] " response
  case "${response,,}" in n|no|nein) return 1 ;; esac
  case "$pm" in
    apt-get) as_root apt-get update && as_root apt-get install -y python3 python3-venv python3-pip curl ca-certificates tar iproute2 ;;
    dnf) as_root dnf install -y python3 python3-pip curl ca-certificates tar iproute ;;
    zypper) as_root zypper --non-interactive install python3 python3-pip python3-virtualenv curl ca-certificates tar iproute2 ;;
    pacman) as_root pacman -Sy --needed --noconfirm python python-pip curl ca-certificates tar iproute2 ;;
    apk) as_root apk add python3 py3-pip py3-virtualenv curl ca-certificates tar iproute2 ;;
  esac
}

ensure_python() {
  if [[ -x "$VENV_PY" ]] && python_ok "$VENV_PY"; then printf '%s\n' "$VENV_PY"; return 0; fi
  local base=""
  base="$(find_python || true)"
  if [[ -z "$base" ]]; then install_linux_packages || { echo "$(text no_python)" >&2; return 1; }; base="$(find_python || true)"; fi
  [[ -n "$base" ]] || { echo "$(text no_python)" >&2; return 1; }
  if ! "$base" -m venv "$VENV_DIR" >/dev/null 2>&1; then
    install_linux_packages || true
    "$base" -m venv "$VENV_DIR"
  fi
  python_ok "$VENV_PY" || { echo "$(text no_python)" >&2; return 1; }
  printf '%s\n' "$VENV_PY"
}

ensure_tool() {
  local tool="$1"
  command -v "$tool" >/dev/null 2>&1 && return 0
  install_linux_packages || return 1
  command -v "$tool" >/dev/null 2>&1
}

invoke_lab() {
  local py; py="$(ensure_python)"
  (cd "$REPO_ROOT" && "$py" "$LAB_HELPER" "$@")
}

json_field() {
  local json="$1" field="$2" py; py="$(ensure_python)"
  "$py" -c 'import json,sys; d=json.loads(sys.argv[1]); v=d.get(sys.argv[2]); print("" if v is None else v)' "$json" "$field"
}

show_summary() {
  local path="$1" kind="$2" py; py="$(ensure_python)"
  "$py" - "$path" "$kind" <<'PY'
import json,sys
from pathlib import Path
p=Path(sys.argv[1]); kind=sys.argv[2]
try:
    if kind=='inventory':
        d=json.loads((p/'node_profile.json').read_text())
        gpu=', '.join(x.get('name','?') for x in d.get('devices',[])) or '-'
        print(f"CPU: {d.get('cpu',{}).get('model','?')}")
        print(f"GPU: {gpu}")
        print(f"RAM: {d.get('memory',{}).get('total_bytes',0)/1024**3:.1f} GB")
    elif kind=='network':
        f=max(p.glob('network_*.json'), key=lambda x:x.stat().st_mtime)
        d=json.loads(f.read_text()); m=d['metrics']
        print(f"RTT p50/p95: {m['rtt_ms_p50']} / {m['rtt_ms_p95']} ms")
        print(f"Upload/Download: {m['upload_mbps_p50']} / {m['download_mbps_p50']} Mbit/s")
    elif kind=='llama':
        ds=[json.loads(x.read_text()) for x in p.glob('benchmark_*.json')]
        pp=next((x for x in ds if x.get('benchmark_name')=='llama_cpp_prefill'),None)
        tg=next((x for x in ds if x.get('benchmark_name')=='llama_cpp_decode'),None)
        if pp: print(f"Prefill: {pp['metrics']['prefill_tokens_per_second_avg']} tokens/s")
        if tg: print(f"Decode: {tg['metrics']['decode_tokens_per_second_avg']} tokens/s, {tg['metrics']['inter_token_ms_avg']} ms/token")
except Exception as e:
    print(f"Summary unavailable: {e}")
PY
}

is_private_ipv4() {
  local ip="$1" py; py="$(ensure_python)"
  "$py" - "$ip" <<'PY' >/dev/null 2>&1
import ipaddress,sys
x=ipaddress.ip_address(sys.argv[1])
nets=[ipaddress.ip_network('10.0.0.0/8'),ipaddress.ip_network('172.16.0.0/12'),ipaddress.ip_network('192.168.0.0/16')]
raise SystemExit(0 if x.version==4 and any(x in n for n in nets) else 1)
PY
}

private_lan_info() {
  ensure_tool ip
  local route dev ip cidr network py
  route="$(ip -4 route get 1.1.1.1 2>/dev/null | head -n1 || true)"
  dev="$(awk '{for(i=1;i<=NF;i++) if($i=="dev") {print $(i+1); exit}}' <<<"$route")"
  ip="$(awk '{for(i=1;i<=NF;i++) if($i=="src") {print $(i+1); exit}}' <<<"$route")"
  if [[ -z "$ip" || -z "$dev" ]] || ! is_private_ipv4 "$ip"; then
    while read -r dev cidr; do ip="${cidr%/*}"; is_private_ipv4 "$ip" && break; done < <(ip -o -4 addr show scope global | awk '{print $2, $4}')
  else
    cidr="$(ip -o -4 addr show dev "$dev" scope global | awk -v ip="$ip" '$4 ~ "^"ip"/" {print $4; exit}')"
  fi
  [[ -n "${ip:-}" && -n "${dev:-}" && -n "${cidr:-}" ]] || return 1
  py="$(ensure_python)"
  network="$($py - "$cidr" <<'PY'
import ipaddress,sys
print(ipaddress.ip_network(sys.argv[1], strict=False))
PY
)"
  printf '%s|%s|%s\n' "$ip" "$dev" "$network"
}

cleanup_firewall() {
  set +e
  case "$FW_KIND" in
    firewalld) as_root firewall-cmd --zone="$FW_ZONE" --remove-rich-rule="$FW_RULE" >/dev/null 2>&1 ;;
    ufw) as_root ufw --force delete allow from "$FW_NETWORK" to "$FW_IP" port "$DEFAULT_PORT" proto tcp >/dev/null 2>&1 ;;
  esac
  FW_KIND=""
  set -e
}

open_temp_firewall() {
  local ip="$1" dev="$2" network="$3" zone
  FW_IP="$ip"; FW_NETWORK="$network"; FW_KIND=""
  if command -v firewall-cmd >/dev/null 2>&1 && systemctl is-active --quiet firewalld 2>/dev/null; then
    zone="$(firewall-cmd --get-zone-of-interface="$dev" 2>/dev/null || true)"; [[ -n "$zone" ]] || zone=public
    FW_ZONE="$zone"; FW_RULE="rule family=ipv4 source address=$network destination address=$ip port port=$DEFAULT_PORT protocol=tcp accept"
    as_root firewall-cmd --zone="$FW_ZONE" --add-rich-rule="$FW_RULE" >/dev/null
    FW_KIND=firewalld
  elif command -v ufw >/dev/null 2>&1 && as_root ufw status 2>/dev/null | grep -q '^Status: active'; then
    as_root ufw allow from "$network" to "$ip" port "$DEFAULT_PORT" proto tcp >/dev/null
    FW_KIND=ufw
  fi
}

node_setup() {
  heading
  local output result path
  output="$(invoke_lab inventory)"; printf '%s\n' "$output"
  result="$(tail -n1 <<<"$output")"; path="$(json_field "$result" path)"
  printf '\n%s: %s\n' "$(text results)" "$path"; show_summary "$path" inventory; pause_ui
}

network_server() {
  heading; echo "$(text private)"; echo "$(text firewall)"
  invoke_lab status >/dev/null
  local info ip dev network
  info="$(private_lan_info)" || { echo 'No RFC1918 LAN interface found.' >&2; return 1; }
  IFS='|' read -r ip dev network <<<"$info"
  printf '\n%s: %s\n%s\n' "$(text ip)" "$ip" "$(text server_help)"
  open_temp_firewall "$ip" "$dev" "$network"
  trap cleanup_firewall EXIT INT TERM
  invoke_lab network-server --bind "$ip" --port "$DEFAULT_PORT"
  cleanup_firewall; trap - EXIT INT TERM
  echo "$(text done)"; pause_ui
}

network_client() {
  heading; echo "$(text private)"
  local ip output result path
  while true; do read -r -p "$(text enter_ip): " ip; is_private_ipv4 "$ip" && break; echo "$(text bad_ip)"; done
  output="$(invoke_lab network-client --host "$ip" --port "$DEFAULT_PORT")"; printf '%s\n' "$output"
  result="$(tail -n1 <<<"$output")"; path="$(json_field "$result" path)"
  printf '\n%s: %s\n' "$(text results)" "$path"; show_summary "$path" network; pause_ui
}

release_asset() {
  local release_json="$1" backend="$2" arch="$3" py; py="$(ensure_python)"
  "$py" - "$release_json" "$backend" "$arch" <<'PY'
import json,re,sys
p,backend,arch=sys.argv[1:]
d=json.load(open(p,encoding='utf-8'))
assets=d.get('assets',[])
if arch in ('x86_64','amd64'): a='x64'
elif arch in ('aarch64','arm64'): a='arm64'
else: raise SystemExit(2)
patterns=[]
if backend=='rocm' and a=='x64': patterns=[rf'bin-ubuntu-rocm-[^-]+-{a}\.tar\.gz$']
elif backend=='vulkan': patterns=[rf'bin-ubuntu-vulkan-{a}\.tar\.gz$']
patterns += [rf'bin-ubuntu-{a}\.tar\.gz$']
for pat in patterns:
  for x in assets:
    if re.search(pat,x.get('name','')):
      print(json.dumps({'tag':d.get('tag_name','latest'),'name':x['name'],'url':x['browser_download_url'],'digest':x.get('digest')})); raise SystemExit(0)
raise SystemExit(1)
PY
}

download_llama() {
  ensure_tool curl; ensure_tool tar
  local py; py="$(ensure_python)"
  local runtime="$REPO_ROOT/artifacts/lab/runtime/llama.cpp"
  local tmp="$runtime/release.json" backend=cpu arch asset tag name url digest dest archive bench wrapper
  mkdir -p "$runtime"
  echo "$(text ubuntu_note)"; echo "$(text download)"
  curl -fsSL --retry 3 --connect-timeout 15 'https://api.github.com/repos/ggml-org/llama.cpp/releases/latest' -o "$tmp"
  arch="$(uname -m)"
  if command -v rocminfo >/dev/null 2>&1; then backend=rocm
  elif command -v vulkaninfo >/dev/null 2>&1 || command -v nvidia-smi >/dev/null 2>&1 || [[ -e /dev/dri/renderD128 ]]; then backend=vulkan
  fi
  asset="$(release_asset "$tmp" "$backend" "$arch" || true)"
  [[ -n "$asset" ]] || { echo "$(text no_asset)" >&2; return 1; }
  tag="$($py -c 'import json,sys;print(json.loads(sys.argv[1])["tag"])' "$asset")"
  name="$($py -c 'import json,sys;print(json.loads(sys.argv[1])["name"])' "$asset")"
  url="$($py -c 'import json,sys;print(json.loads(sys.argv[1])["url"])' "$asset")"
  digest="$($py -c 'import json,sys;print(json.loads(sys.argv[1]).get("digest") or "")' "$asset")"
  dest="$runtime/$tag-$backend-$(uname -m)"; archive="$runtime/$name"
  mkdir -p "$dest"; curl -fL --retry 3 --connect-timeout 15 "$url" -o "$archive"
  if [[ "$digest" == sha256:* ]] && command -v sha256sum >/dev/null 2>&1; then
    printf '%s  %s\n' "${digest#sha256:}" "$archive" | sha256sum -c -
  fi
  tar -xzf "$archive" -C "$dest"
  bench="$(find "$dest" -type f -name llama-bench -print -quit)"; [[ -n "$bench" ]] || return 1; chmod +x "$bench"
  wrapper="$dest/llama-bench-computemesh"
  {
    echo '#!/usr/bin/env bash'; echo 'set -Eeuo pipefail'; printf 'BENCH=%q\n' "$bench"; printf 'BASE=%q\n' "$dest";
    echo 'export LD_LIBRARY_PATH="$(dirname "$BENCH"):$BASE:$BASE/lib:$BASE/build/bin:${LD_LIBRARY_PATH:-}"'; echo 'exec "$BENCH" "$@"'
  } > "$wrapper"; chmod +x "$wrapper"
  if ! "$wrapper" --help >/dev/null 2>&1; then echo 'Downloaded llama-bench could not run on this distribution. Choose an existing compatible build.' >&2; return 1; fi
  printf '%s\n' "$wrapper"
}

choose_existing_llama() {
  local status saved path
  status="$(invoke_lab status | tail -n1)"; saved="$(json_field "$status" llama_bench)"
  if [[ -n "$saved" && -x "$saved" ]]; then read -r -p "Use saved llama-bench: $saved ? [Y/n] " path; case "${path,,}" in n|no|nein) ;; *) echo "$saved"; return 0 ;; esac; fi
  if command -v llama-bench >/dev/null 2>&1; then echo "$(command -v llama-bench)"; return 0; fi
  read -r -e -p 'llama-bench path: ' path; path="${path%\"}"; path="${path#\"}"; [[ -x "$path" ]] || return 1; echo "$path"
}

choose_model() {
  local status saved path
  status="$(invoke_lab status | tail -n1)"; saved="$(json_field "$status" model_path)"
  if [[ -n "$saved" && -f "$saved" ]]; then read -r -p "Use saved model: $saved ? [Y/n] " path; case "${path,,}" in n|no|nein) ;; *) echo "$saved"; return 0 ;; esac; fi
  if command -v zenity >/dev/null 2>&1 && [[ -n "${DISPLAY:-}${WAYLAND_DISPLAY:-}" ]]; then path="$(zenity --file-selection --title="$(text model)" --file-filter='GGUF | *.gguf' 2>/dev/null || true)"; [[ -f "$path" ]] && { echo "$path"; return 0; }; fi
  read -r -e -p "$(text model): " path; path="${path%\"}"; path="${path#\"}"; [[ -f "$path" ]] || return 1; echo "$path"
}

llama_setup() {
  heading; invoke_lab status >/dev/null
  local choice exe model output result path
  echo "1. $(text auto_llama)"; echo "2. $(text existing_llama)"; read -r -p "$(text choice) [1]: " choice; choice="${choice:-1}"
  if [[ "$choice" == 1 ]]; then exe="$(download_llama)"; else exe="$(choose_existing_llama)"; fi
  model="$(choose_model)"
  output="$(invoke_lab llama --llama-bench "$exe" --model "$model")"; printf '%s\n' "$output"
  result="$(tail -n1 <<<"$output")"; path="$(json_field "$result" path)"
  printf '\n%s: %s\n' "$(text results)" "$path"; show_summary "$path" llama; pause_ui
}

all_tests() {
  heading; local py; py="$(ensure_python)"
  (cd "$REPO_ROOT" && "$py" -m pip install -r requirements-dev.txt && "$py" "$LAB_HELPER" tests)
  echo "$(text done)"; pause_ui
}

show_menu() {
  while true; do
    heading; echo "$(text menu)"; echo
    echo "1. $(text node)"; echo "2. $(text server)"; echo "3. $(text client)"; echo "4. $(text llama)"; echo "5. $(text tests)"; echo "0. $(text exit)"
    read -r -p "$(text choice): " choice
    case "$choice" in 1) node_setup ;; 2) network_server ;; 3) network_client ;; 4) llama_setup ;; 5) all_tests ;; 0) return 0 ;; esac
  done
}

main() {
  case "$MODE" in
    menu) show_menu ;;
    node) node_setup ;;
    network-server|server) network_server ;;
    network-client|client) network_client ;;
    llama) llama_setup ;;
    tests) all_tests ;;
    help|-h|--help) printf 'Usage: ./setup.sh [menu|node|server|client|llama|tests]\n' ;;
    *) echo "Unknown mode: $MODE" >&2; return 2 ;;
  esac
}

if [[ "${BASH_SOURCE[0]}" == "$0" ]]; then main "$@"; fi
