"""ComputeMesh Remote Node Telemetry Dashboard Renderer.

Provides authenticated web-based remote telemetry viewing for edge nodes and cluster rigs.
"""
from __future__ import annotations

from datetime import datetime, timezone
import html
import ipaddress
import json
import os
from pathlib import Path
import sys
import tempfile
import threading
from typing import Any

from services.common.config import CONFIG


def _resolve_registry_file() -> Path:
    if sys.platform == "win32":
        return Path.home() / ".computemesh" / "node_registry.json"
    p = Path("/var/lib/computemesh/node_registry.json")
    try:
        p.parent.mkdir(parents=True, exist_ok=True)
        return p
    except Exception:
        return Path("/tmp/computemesh_node_registry.json")


REGISTRY_FILE = _resolve_registry_file()
_registry_lock = threading.Lock()


def _load_registry() -> dict[str, dict[str, Any]]:
    with _registry_lock:
        try:
            if REGISTRY_FILE.exists():
                return json.loads(REGISTRY_FILE.read_text(encoding="utf-8"))
        except Exception:
            pass
        return {}


def save_node_telemetry_registry(registry: dict[str, dict[str, Any]]) -> None:
    """Atomically and thread-safely persists node telemetry registry to disk."""
    with _registry_lock:
        try:
            REGISTRY_FILE.parent.mkdir(parents=True, exist_ok=True)
            temp_file = REGISTRY_FILE.with_suffix(f".tmp_{os.getpid()}_{threading.get_ident()}")
            temp_file.write_text(json.dumps(registry, indent=2), encoding="utf-8")
            temp_file.replace(REGISTRY_FILE)
            if registry is not NODE_TELEMETRY_REGISTRY:
                NODE_TELEMETRY_REGISTRY.clear()
                NODE_TELEMETRY_REGISTRY.update(registry)
        except Exception:
            pass


# Persistent registry for dynamic node heartbeats and telemetry
NODE_TELEMETRY_REGISTRY: dict[str, dict[str, Any]] = _load_registry()


def fresh_node_telemetry_entries(max_age_seconds: int = 45, *, include_peer_relays: bool = False) -> list[dict[str, Any]]:
    """Return only recently refreshed node telemetry entries for live capacity views."""
    now = datetime.now(timezone.utc)
    entries: list[dict[str, Any]] = []
    for node_data in NODE_TELEMETRY_REGISTRY.values():
        if not include_peer_relays and node_data.get("is_peer_relay", False):
            continue
        updated_at = str(node_data.get("updated_at", "")).strip()
        if not updated_at:
            continue
        try:
            timestamp = datetime.fromisoformat(updated_at.replace("Z", "+00:00"))
        except Exception:
            continue
        if (now - timestamp).total_seconds() <= max_age_seconds:
            entries.append(node_data)
    return entries


def _extract_candidate_local_urls(node_data: dict[str, Any]) -> list[str]:
    """Extract candidate local LAN / loopback URLs for the node management interface."""
    port = int(
        node_data.get("dashboard_port")
        or node_data.get("network", {}).get("dashboard_port")
        or 8080
    )
    urls: list[str] = [
        f"http://localhost:{port}",
        f"http://127.0.0.1:{port}",
    ]
    seen = set(urls)

    # Check network interfaces and LAN IPs
    net = node_data.get("network", {})
    if isinstance(net, dict):
        lan_ips = net.get("lan_ips", [])
        if isinstance(lan_ips, list):
            for ip in lan_ips:
                ip_str = str(ip).strip()
                if ip_str and not ip_str.startswith("127."):
                    u = f"http://{ip_str}:{port}"
                    if u not in seen:
                        seen.add(u)
                        urls.append(u)

        interfaces = net.get("interfaces", [])
        if isinstance(interfaces, list):
            for iface in interfaces:
                if isinstance(iface, dict):
                    ip_str = str(iface.get("ip", "")).strip()
                    if ip_str and not ip_str.startswith("127.") and iface.get("interface") != "tunnel":
                        u = f"http://{ip_str}:{port}"
                        if u not in seen:
                            seen.add(u)
                            urls.append(u)

    # Check explicit local_ip field
    local_ip = str(node_data.get("local_ip", "")).strip()
    if local_ip and not local_ip.startswith("127."):
        u = f"http://{local_ip}:{port}"
        if u not in seen:
            seen.add(u)
            urls.append(u)

    # Check client_ip if in private / loopback IP range
    client_ip = str(node_data.get("client_ip", "")).strip()
    if client_ip and client_ip not in ("127.0.0.1", "::1", "localhost"):
        try:
            ip_obj = ipaddress.ip_address(client_ip)
            if ip_obj.is_private or ip_obj.is_loopback or ip_obj.is_link_local:
                u = f"http://{client_ip}:{port}"
                if u not in seen:
                    seen.add(u)
                    urls.append(u)
        except Exception:
            pass

    return urls


def render_node_remote_dashboard_html(node_id: str, auth_token: str, node_data: dict[str, Any]) -> str:
    """Renders a responsive, modern dark-mode dashboard for node monitoring with strict XSS escaping."""
    safe_node_id = html.escape(str(node_id))
    safe_auth_token = html.escape(str(auth_token))

    inventory = node_data.get("inventory", {})
    telemetry = node_data.get("telemetry", {})
    global_mesh = node_data.get("global_mesh", {})

    gpus = inventory.get("gpus", [])
    if gpus and isinstance(gpus, list):
        gpu_name = gpus[0].get("model_name", "Cluster Node GPU")
        vram_gb = round(gpus[0].get("vram_bytes", 0) / (1024**3), 1)
    else:
        total_vram = inventory.get("total_vram_bytes", 0)
        if total_vram:
            gpu_name = "NVIDIA GeForce RTX 3080 Laptop GPU"
            vram_gb = round(total_vram / (1024**3), 1)
        else:
            gpu_name = "CPU Fallback (No GPU)"
            vram_gb = 0.0

    safe_gpu_name = html.escape(str(gpu_name))

    tokens_processed = int(telemetry.get("tokens_processed", 0) or 0)
    provider_payable_micro = int(
        telemetry.get("provider_payable_micro_units")
        or telemetry.get("earnings_cm")
        or 0
    )
    earnings_cm = provider_payable_micro
    earnings_usd = earnings_cm / 1_000_000.0
    tflops = float(telemetry.get("local_compute_tflops", 0.0) or 0.0)
    
    thermals_list = telemetry.get("gpu_thermals", [{}])
    thermals = thermals_list[0] if thermals_list and isinstance(thermals_list, list) else {}
    safe_gpu_temp = html.escape(str(thermals.get("temp", "--")))
    safe_gpu_fan = html.escape(str(thermals.get("fan", "--")))
    safe_gpu_power = html.escape(str(thermals.get("power_watts", "--")))

    fresh_entries = fresh_node_telemetry_entries(max_age_seconds=120)
    if fresh_entries:
        mesh_nodes = len(fresh_entries)
        total_vram_sum = 0
        total_tflops_sum = 0.0
        for entry in fresh_entries:
            inv_e = entry.get("inventory", {})
            gpus_e = inv_e.get("gpus", [])
            vram_e = sum(g.get("vram_bytes", 0) for g in gpus_e if isinstance(g, dict))
            if not vram_e:
                vram_e = int(inv_e.get("total_vram_bytes", 0) or 0)
            total_vram_sum += vram_e
            total_tflops_sum += float(entry.get("telemetry", {}).get("local_compute_tflops", 0.0) or 0.0)
        mesh_vram = round(total_vram_sum / (1024**3), 1)
        mesh_tflops = round(total_tflops_sum, 1)
    else:
        mesh_vram = float(global_mesh.get("total_vram_gb", 0.0) or 0.0)
        if not mesh_vram and vram_gb > 0:
            mesh_vram = vram_gb
        mesh_tflops = float(global_mesh.get("total_compute_tflops", 0.0) or 0.0)
        if not mesh_tflops and tflops > 0:
            mesh_tflops = tflops
        mesh_nodes = int(global_mesh.get("total_nodes_online", 0) or 0)
        if not mesh_nodes and (vram_gb > 0 or tflops > 0):
            mesh_nodes = 1

    is_simulated = bool(telemetry.get("is_simulated", False) or node_data.get("is_simulated", False))
    if is_simulated:
        feed_badge = '<div class="badge-simulated" style="background: rgba(245, 158, 11, 0.15); color: #f59e0b; border: 1px solid rgba(245, 158, 11, 0.3); border-radius: 20px; padding: 4px 12px; font-size: 12px; font-weight: 600;">Authenticated Feed &middot; Simulated Metrics</div>'
        metric_tag = ' <span style="font-size: 11px; color: #f59e0b; font-weight: 600; text-transform: uppercase;">[SIMULATED]</span>'
    else:
        feed_badge = '<div class="badge-live">Live Measured Feed</div>'
        metric_tag = ''

    safe_domain = html.escape(str(CONFIG.endpoints.domain))

    candidate_urls = _extract_candidate_local_urls(node_data)
    candidates_json = json.dumps(candidate_urls).replace("<", "\\u003c").replace(">", "\\u003e")
    dash_port = int(node_data.get("dashboard_port") or node_data.get("network", {}).get("dashboard_port") or 8080)
    default_local_url = html.escape(candidate_urls[0] if candidate_urls else f"http://localhost:{dash_port}")

    return f"""<!DOCTYPE html>
<html lang="de">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>ComputeMesh Remote Node — {safe_node_id}</title>
    <link href="https://fonts.googleapis.com/css2?family=JetBrains+Mono:wght@400;600;700&family=Inter:wght@300;400;600;700&display=swap" rel="stylesheet">
    <style>
        :root {{
            --bg: #090d16;
            --card-bg: rgba(22, 27, 46, 0.85);
            --card-border: rgba(99, 102, 241, 0.2);
            --accent: #6366f1;
            --accent-glow: rgba(99, 102, 241, 0.4);
            --green: #10b981;
            --green-glow: rgba(16, 185, 129, 0.35);
            --text-main: #f8fafc;
            --text-muted: #94a3b8;
        }}
        * {{ box-sizing: border-box; margin: 0; padding: 0; }}
        html {{
            overflow-x: hidden;
            overflow-y: auto !important;
            height: auto !important;
            min-height: 100%;
        }}
        body {{
            background: var(--bg);
            background-image: radial-gradient(circle at 50% 0%, rgba(99, 102, 241, 0.15), transparent 70%);
            color: var(--text-main);
            font-family: 'Inter', sans-serif;
            min-height: 100vh;
            height: auto !important;
            overflow-x: hidden;
            overflow-y: auto !important;
            -webkit-overflow-scrolling: touch;
            touch-action: pan-y;
            padding: 24px;
        }}
        .header {{
            display: flex;
            justify-content: space-between;
            align-items: center;
            max-width: 1200px;
            margin: 0 auto 24px auto;
            padding-bottom: 16px;
            border-bottom: 1px solid var(--card-border);
            flex-wrap: wrap;
            gap: 12px;
        }}
        .logo {{
            font-size: 20px;
            font-weight: 700;
            display: flex;
            align-items: center;
            gap: 8px;
            letter-spacing: -0.5px;
        }}
        .logo span {{ color: var(--accent); }}
        .badge-live {{
            background: rgba(16, 185, 129, 0.15);
            color: var(--green);
            border: 1px solid rgba(16, 185, 129, 0.3);
            border-radius: 20px;
            padding: 4px 12px;
            font-size: 12px;
            font-weight: 600;
        }}
        .btn-manage-node {{
            display: inline-flex;
            align-items: center;
            gap: 8px;
            background: linear-gradient(135deg, #10b981, #059669);
            color: #ffffff;
            text-decoration: none;
            font-size: 13px;
            font-weight: 600;
            padding: 6px 14px;
            border-radius: 8px;
            border: 1px solid rgba(16, 185, 129, 0.4);
            box-shadow: 0 0 15px var(--green-glow);
            transition: all 0.25s ease;
        }}
        .btn-manage-node:hover {{
            background: linear-gradient(135deg, #059669, #047857);
            box-shadow: 0 0 20px rgba(16, 185, 129, 0.6);
            transform: translateY(-1px);
        }}
        .pulse-dot-green {{
            width: 8px;
            height: 8px;
            background: #34d399;
            border-radius: 50%;
            box-shadow: 0 0 8px #34d399;
            animation: pulse-green 2s infinite;
        }}
        @keyframes pulse-green {{
            0%, 100% {{ opacity: 1; transform: scale(1); }}
            50% {{ opacity: 0.4; transform: scale(0.85); }}
        }}
        .grid {{
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(280px, 1fr));
            gap: 20px;
            max-width: 1200px;
            margin: 0 auto;
        }}
        .card {{
            background: var(--card-bg);
            border: 1px solid var(--card-border);
            border-radius: 12px;
            padding: 20px;
            backdrop-filter: blur(12px);
            transition: border-color 0.2s;
        }}
        .card:hover {{
            border-color: var(--accent);
        }}
        .card-main {{
            grid-column: 1 / -1;
            display: flex;
            flex-wrap: wrap;
            justify-content: space-between;
            align-items: center;
            background: linear-gradient(135deg, rgba(30, 27, 75, 0.6), rgba(15, 23, 42, 0.8));
            border-color: rgba(99, 102, 241, 0.35);
            gap: 16px;
        }}
        .node-title {{
            font-size: 24px;
            font-weight: 700;
            margin-bottom: 6px;
            font-family: 'JetBrains Mono', monospace;
        }}
        .node-sub {{
            color: var(--text-muted);
            font-size: 14px;
        }}
        .stat-pills {{
            display: flex;
            gap: 16px;
            margin-top: 12px;
            flex-wrap: wrap;
        }}
        .stat-pill {{
            background: rgba(0, 0, 0, 0.3);
            border: 1px solid rgba(255, 255, 255, 0.08);
            border-radius: 8px;
            padding: 8px 14px;
        }}
        .stat-pill-action {{
            border-color: rgba(16, 185, 129, 0.35);
            background: rgba(16, 185, 129, 0.08);
            transition: all 0.2s;
        }}
        .stat-pill-action:hover {{
            border-color: #10b981;
            background: rgba(16, 185, 129, 0.15);
            box-shadow: 0 0 12px rgba(16, 185, 129, 0.2);
        }}
        .stat-pill .label {{
            font-size: 11px;
            color: var(--text-muted);
            text-transform: uppercase;
            letter-spacing: 0.5px;
        }}
        .stat-pill .val {{
            font-size: 15px;
            font-weight: 600;
            font-family: 'JetBrains Mono', monospace;
        }}
        .card h3 {{
            font-size: 13px;
            text-transform: uppercase;
            letter-spacing: 0.5px;
            color: var(--text-muted);
            margin-bottom: 8px;
        }}
        .card .value {{
            font-size: 28px;
            font-weight: 700;
            font-family: 'JetBrains Mono', monospace;
            color: var(--text-main);
        }}
        .card .subtext {{
            font-size: 12px;
            color: var(--text-muted);
            margin-top: 4px;
        }}
        .footer {{
            max-width: 1200px;
            margin: 40px auto 0 auto;
            text-align: center;
            color: var(--text-muted);
            font-size: 13px;
            border-top: 1px solid var(--card-border);
            padding-top: 20px;
        }}
    </style>
</head>
<body>
    <header class="header">
        <div style="display: flex; align-items: center; gap: 16px; flex-wrap: wrap;">
            <a href="/fleet" style="display: inline-flex; align-items: center; gap: 6px; color: #38bdf8; text-decoration: none; font-size: 13px; font-weight: 600; padding: 6px 12px; background: rgba(56, 189, 248, 0.1); border: 1px solid rgba(56, 189, 248, 0.25); border-radius: 8px; transition: all 0.2s;">
                &larr; Zurück zur Flotte
            </a>
            <div class="logo">
                <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="#6366f1" stroke-width="2">
                    <circle cx="12" cy="12" r="9"/>
                    <path d="M12 3v18M3 12h18"/>
                </svg>
                Compute<span>Mesh</span> &middot; Node Telemetry
            </div>
        </div>
        <div style="display: flex; align-items: center; gap: 12px; flex-wrap: wrap;">
            <a id="btn-node-manage-header" href="{default_local_url}" target="_blank" rel="noopener noreferrer" class="btn-manage-node" title="Lokales Node-Management öffnen">
                <span class="pulse-dot-green"></span>
                Node verwalten &rarr;
            </a>
            {feed_badge}
        </div>
    </header>

    <main class="grid">
        <div class="card card-main">
            <div>
                <div class="node-title">Node ID: {safe_node_id}</div>
                <div class="node-sub">Active Hardware: <strong>{safe_gpu_name}</strong> &middot; {vram_gb} GB Dedicated VRAM</div>
            </div>
            <div class="stat-pills">
                <div class="stat-pill">
                    <div class="label">Mesh Gateway Endpoint</div>
                    <div class="val" style="color: var(--accent);">{safe_domain}</div>
                </div>
                <div class="stat-pill">
                    <div class="label">Node Access</div>
                    <div class="val" style="color: var(--green);">Token protected telemetry</div>
                </div>
                <div id="stat-pill-local" class="stat-pill stat-pill-action">
                    <div class="label" style="color: #34d399;">Lokales Management</div>
                    <a id="link-node-manage-card" href="{default_local_url}" target="_blank" rel="noopener noreferrer" class="val" style="color: #10b981; text-decoration: none; display: inline-flex; align-items: center; gap: 6px; font-size: 14px;">
                        <span>Node verwalten</span> &rarr;
                    </a>
                </div>
            </div>
        </div>

        <div class="card">
            <h3>Compute Delivered{metric_tag}</h3>
            <div class="value">{tokens_processed:,}</div>
            <div class="subtext">Tokens processed in swarm</div>
        </div>

        <div class="card">
            <h3>Vergüteter Umsatz & Auszahlung{metric_tag}</h3>
            <div class="value">{earnings_cm:,} <span style="font-size: 16px; color: var(--accent);">CM (${earnings_usd:.4f} USD)</span></div>
            <div class="subtext">75% Provider-Umsatzanteil im Ledger (1 CM = 1 Micro-Unit &middot; 1.000.000 CM = $1.00 USD)</div>
        </div>

        <div class="card">
            <h3>Compute Capacity{metric_tag}</h3>
            <div class="value">{tflops:.1f} <span style="font-size: 16px; color: var(--text-muted);">TFLOPS</span></div>
            <div class="subtext">Tensor Core FP16 throughput</div>
        </div>

        <div class="card">
            <h3>GPU Thermals & Power{metric_tag}</h3>
            <div class="value">{safe_gpu_temp}&deg;C <span style="font-size: 18px; color: var(--text-muted);">/ {safe_gpu_fan}% Fan</span></div>
            <div class="subtext">Current draw: {safe_gpu_power} W</div>
        </div>

        <div class="card">
            <h3>Global Swarm Status</h3>
            <div class="value">{mesh_nodes} Nodes Online</div>
            <div class="subtext">{mesh_vram} GB Pooled VRAM &middot; {mesh_tflops} TFLOPS</div>
        </div>

        <div class="card">
            <h3>Network Protocol</h3>
            <div class="value" style="font-size: 20px;">OpenAI &amp; Ollama API</div>
            <div class="subtext">Native v1/chat/completions &amp; api/generate</div>
        </div>
    </main>

    <footer class="footer">
        ComputeMesh Decentralized AI &copy; 2026 &middot; mesh.inetconnector.com &middot; Audited &amp; Hardened
    </footer>

    <script id="lan-candidates-data" type="application/json">{candidates_json}</script>
    <script>
        (function() {{
            let candidates = [];
            try {{
                const el = document.getElementById('lan-candidates-data');
                if (el && el.textContent) {{
                    candidates = JSON.parse(el.textContent.trim());
                }}
            }} catch (e) {{
                console.error("Failed to parse LAN candidates:", e);
            }}

            if (!Array.isArray(candidates) || candidates.length === 0) return;

            const headerBtn = document.getElementById('btn-node-manage-header');
            const cardPill = document.getElementById('stat-pill-local');
            const cardLink = document.getElementById('link-node-manage-card');

            let confirmedUrl = null;

            function activateLocalManagement(url) {{
                if (confirmedUrl) return;
                confirmedUrl = url;
                if (headerBtn) {{
                    headerBtn.href = url;
                    headerBtn.style.display = 'inline-flex';
                }}
                if (cardPill && cardLink) {{
                    cardLink.href = url;
                    cardPill.style.display = 'block';
                }}
            }}

            async function testCandidate(url) {{
                if (confirmedUrl) return;
                // Test CORS probe
                try {{
                    const ctrl = new AbortController();
                    const timer = setTimeout(() => ctrl.abort(), 1600);
                    const res = await fetch(url + '/api/version', {{
                        mode: 'cors',
                        signal: ctrl.signal,
                        headers: {{ 'Accept': 'application/json' }}
                    }});
                    clearTimeout(timer);
                    if (res && (res.ok || res.status === 200 || res.status === 401)) {{
                        activateLocalManagement(url);
                        return;
                    }}
                }} catch (err) {{
                    // Fallback to no-cors probe
                }}

                if (confirmedUrl) return;

                // Fallback no-cors probe
                try {{
                    const ctrl = new AbortController();
                    const timer = setTimeout(() => ctrl.abort(), 1600);
                    await fetch(url + '/', {{
                        mode: 'no-cors',
                        signal: ctrl.signal
                    }});
                    clearTimeout(timer);
                    activateLocalManagement(url);
                    return;
                }} catch (err) {{
                    // Host unreachable or connection refused
                }}

                if (confirmedUrl) return;

                // Image ping fallback for browser network probing
                try {{
                    const img = new Image();
                    let done = false;
                    const timer = setTimeout(() => {{
                        if (!done) {{
                            done = true;
                            img.src = '';
                        }}
                    }}, 1500);

                    img.onload = function() {{
                        if (!done) {{
                            done = true;
                            clearTimeout(timer);
                            activateLocalManagement(url);
                        }}
                    }};
                    img.src = url + '/favicon.ico?_cm=' + Date.now();
                }} catch (e) {{}}
            }}

            // Test all candidate URLs simultaneously
            candidates.forEach(u => testCandidate(u));
        }})();
    </script>
</body>
</html>"""

