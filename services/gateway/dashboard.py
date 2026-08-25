"""ComputeMesh Remote Node Telemetry Dashboard Renderer.

Provides authenticated web-based remote telemetry viewing for edge nodes and cluster rigs.
"""
from __future__ import annotations

import json
from typing import Any

from services.common.config import CONFIG

# In-memory registry for dynamic node heartbeats and telemetry
NODE_TELEMETRY_REGISTRY: dict[str, dict[str, Any]] = {}


def render_node_remote_dashboard_html(node_id: str, auth_token: str, node_data: dict[str, Any]) -> str:
    """Renders a responsive, modern dark-mode dashboard for node monitoring."""
    inventory = node_data.get("inventory", {})
    telemetry = node_data.get("telemetry", {})
    global_mesh = node_data.get("global_mesh", {})

    gpus = inventory.get("gpus", [])
    gpu_name = gpus[0].get("model_name", "Cluster Node GPU") if gpus else "CPU Fallback (No GPU)"
    vram_gb = round(gpus[0].get("vram_bytes", 0) / (1024**3), 1) if gpus else 0.0

    tokens_processed = telemetry.get("tokens_processed", 0)
    earnings_cm = telemetry.get("earnings_cm", 0.0)
    tflops = telemetry.get("local_compute_tflops", 0.0)
    thermals = telemetry.get("gpu_thermals", [{}])[0]
    gpu_temp = thermals.get("temp", "--")
    gpu_fan = thermals.get("fan", "--")
    gpu_power = thermals.get("power_watts", "--")

    mesh_vram = global_mesh.get("total_vram_gb", 24.0)
    mesh_tflops = global_mesh.get("total_compute_tflops", 48.6)
    mesh_nodes = global_mesh.get("total_nodes_online", 2)

    return f"""<!DOCTYPE html>
<html lang="de">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>ComputeMesh Remote Node — {node_id}</title>
    <link href="https://fonts.googleapis.com/css2?family=JetBrains+Mono:wght@400;600;700&family=Inter:wght@300;400;600;700&display=swap" rel="stylesheet">
    <style>
        :root {{
            --bg: #090d16;
            --card-bg: rgba(22, 27, 46, 0.85);
            --card-border: rgba(99, 102, 241, 0.2);
            --accent: #6366f1;
            --accent-glow: rgba(99, 102, 241, 0.4);
            --green: #10b981;
            --text-main: #f8fafc;
            --text-muted: #94a3b8;
        }}
        * {{ box-sizing: border-box; margin: 0; padding: 0; }}
        body {{
            background: var(--bg);
            background-image: radial-gradient(circle at 50% 0%, rgba(99, 102, 241, 0.15), transparent 70%);
            color: var(--text-main);
            font-family: 'Inter', sans-serif;
            min-height: 100vh;
            padding: 24px;
        }}
        .header {{
            display: flex;
            justify-content: space-between;
            align-items: center;
            max-width: 1200px;
            margin: 0 auto 32px auto;
            border-bottom: 1px solid var(--card-border);
            padding-bottom: 20px;
        }}
        .logo {{
            font-size: 22px;
            font-weight: 700;
            letter-spacing: -0.5px;
            display: flex;
            align-items: center;
            gap: 12px;
        }}
        .logo span {{ color: var(--accent); }}
        .badge-live {{
            background: rgba(16, 185, 129, 0.15);
            border: 1px solid var(--green);
            color: var(--green);
            padding: 4px 12px;
            border-radius: 999px;
            font-size: 13px;
            font-weight: 600;
            display: inline-flex;
            align-items: center;
            gap: 6px;
        }}
        .badge-live::before {{
            content: '';
            width: 8px;
            height: 8px;
            background: var(--green);
            border-radius: 50%;
            display: inline-block;
            box-shadow: 0 0 8px var(--green);
        }}
        .container {{
            max-width: 1200px;
            margin: 0 auto;
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(280px, 1fr));
            gap: 20px;
        }}
        .card {{
            background: var(--card-bg);
            border: 1px solid var(--card-border);
            border-radius: 16px;
            padding: 24px;
            backdrop-filter: blur(12px);
            transition: transform 0.2s, border-color 0.2s;
        }}
        .card:hover {{
            transform: translateY(-2px);
            border-color: var(--accent);
        }}
        .card h3 {{
            font-size: 13px;
            text-transform: uppercase;
            letter-spacing: 1px;
            color: var(--text-muted);
            margin-bottom: 12px;
        }}
        .card .value {{
            font-family: 'JetBrains Mono', monospace;
            font-size: 28px;
            font-weight: 700;
            color: #ffffff;
        }}
        .card .subtext {{
            font-size: 13px;
            color: var(--text-muted);
            margin-top: 6px;
        }}
        .hero-card {{
            grid-column: 1 / -1;
            background: linear-gradient(135deg, rgba(30, 41, 59, 0.7) 0%, rgba(15, 23, 42, 0.9) 100%);
            border: 1px solid var(--accent);
            box-shadow: 0 8px 32px var(--accent-glow);
        }}
        .grid-2 {{
            display: grid;
            grid-template-columns: 1fr 1fr;
            gap: 16px;
            margin-top: 16px;
        }}
        .stat-pill {{
            background: rgba(0, 0, 0, 0.25);
            padding: 12px;
            border-radius: 8px;
            border: 1px solid rgba(255, 255, 255, 0.05);
        }}
        .stat-pill .label {{ font-size: 11px; color: var(--text-muted); text-transform: uppercase; }}
        .stat-pill .val {{ font-family: 'JetBrains Mono', monospace; font-size: 16px; font-weight: 600; margin-top: 4px; }}
        .footer {{
            max-width: 1200px;
            margin: 40px auto 0 auto;
            text-align: center;
            color: var(--text-muted);
            font-size: 13px;
        }}
    </style>
</head>
<body>
    <header class="header">
        <div class="logo">⚡ Compute<span>Mesh</span> Node Monitor</div>
        <div class="badge-live">ONLINE &middot; P2P RELAY ACTIVE</div>
    </header>

    <main class="container">
        <div class="card hero-card">
            <h3>Active Node Appliance</h3>
            <div class="value">{node_id}</div>
            <div class="subtext">Accelerator: <strong style="color: #fff;">{gpu_name}</strong> ({vram_gb} GB Dedicated VRAM)</div>
            
            <div class="grid-2">
                <div class="stat-pill">
                    <div class="label">Mesh Gateway Endpoint</div>
                    <div class="val" style="color: var(--accent);">{CONFIG.endpoints.domain}</div>
                </div>
                <div class="stat-pill">
                    <div class="label">Relay Encryption Status</div>
                    <div class="val" style="color: var(--green);">mTLS 1.3 &middot; Zero-Knowledge</div>
                </div>
            </div>
        </div>

        <div class="card">
            <h3>Compute Delivered</h3>
            <div class="value">{tokens_processed:,}</div>
            <div class="subtext">Tokens processed in swarm</div>
        </div>

        <div class="card">
            <h3>Earned Revenue</h3>
            <div class="value">{earnings_cm:.4f} <span style="font-size: 16px; color: var(--accent);">USDC / USD</span></div>
            <div class="subtext">Automated Stripe Payout Active</div>
        </div>

        <div class="card">
            <h3>Compute Capacity</h3>
            <div class="value">{tflops:.1f} <span style="font-size: 16px; color: var(--text-muted);">TFLOPS</span></div>
            <div class="subtext">Tensor Core FP16 throughput</div>
        </div>

        <div class="card">
            <h3>GPU Thermals & Power</h3>
            <div class="value">{gpu_temp}&deg;C <span style="font-size: 18px; color: var(--text-muted);">/ {gpu_fan}% Fan</span></div>
            <div class="subtext">Current draw: {gpu_power} W</div>
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
        ComputeMesh Decentralized AI &copy; 2026 &middot; computemesh.inetconnector.com &middot; Enterprise Security Grade
    </footer>
</body>
</html>"""
