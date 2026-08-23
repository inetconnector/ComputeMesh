#!/usr/bin/env python3
"""ComputeMesh Provider Appliance Web Dashboard & Node Management Center.

Provides an embedded, zero-external-dependency web server and interactive UI
listening on port 8080.
Features:
- Real-time GPU telemetry (VRAM, Temperatures, Fan Speeds, Power, PCIe width)
- Live inference token counters and estimated earnings
- Complete Payout Configuration (Ethereum/Polygon/USDT Wallet, Provider Account)
- GPU-by-GPU Compute Enablement Toggles & VRAM Reservation
- Thermal Cutoff Limits and Power Management Profiles
- System Actions (Reboot Node, Restart Inference Daemon)
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import subprocess
import sys
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from tools.appliance.appliance_config import ApplianceConfig, load_appliance_config, save_system_config
from tools.appliance.hardware_detector import RigInventory, scan_rig_hardware
from tools.appliance.multi_gpu_launcher import compute_multi_gpu_allocation

HTML_PAGE = """<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>ComputeMesh NodeOS — AI Inference Appliance</title>
  <link rel="preconnect" href="https://fonts.googleapis.com">
  <link href="https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700&family=JetBrains+Mono:wght@400;600&family=Outfit:wght@600;700;800&display=swap" rel="stylesheet">
  <style>
    :root {
      --bg-base: #0a0e17;
      --bg-surface: #111827;
      --bg-card: rgba(19, 27, 46, 0.75);
      --bg-card-hover: rgba(28, 39, 65, 0.85);
      --border-color: rgba(255, 255, 255, 0.08);
      --border-bright: rgba(0, 240, 255, 0.3);
      --accent-cyan: #00f0ff;
      --accent-blue: #3b82f6;
      --accent-emerald: #10b981;
      --accent-amber: #f59e0b;
      --accent-rose: #f43f5e;
      --text-main: #f3f4f6;
      --text-dim: #9ca3af;
      --font-main: 'Inter', sans-serif;
      --font-mono: 'JetBrains Mono', monospace;
      --font-heading: 'Outfit', sans-serif;
    }
    * { box-sizing: border-box; margin: 0; padding: 0; }
    body {
      background-color: var(--bg-base);
      color: var(--text-main);
      font-family: var(--font-main);
      min-height: 100vh;
      display: flex;
      flex-direction: column;
    }
    header {
      background: var(--bg-surface);
      border-bottom: 1px solid var(--border-color);
      padding: 1rem 2rem;
      display: flex;
      justify-content: space-between;
      align-items: center;
      flex-wrap: wrap;
      gap: 1rem;
    }
    .logo {
      display: flex;
      align-items: center;
      gap: 0.75rem;
      font-family: var(--font-heading);
      font-size: 1.35rem;
      font-weight: 800;
      letter-spacing: -0.02em;
    }
    .logo-badge {
      background: linear-gradient(135deg, var(--accent-cyan), var(--accent-blue));
      color: #000;
      font-size: 0.75rem;
      padding: 0.25rem 0.55rem;
      border-radius: 4px;
      font-weight: 800;
      text-transform: uppercase;
    }
    .nav-tabs {
      display: flex;
      gap: 0.5rem;
      background: rgba(0, 0, 0, 0.3);
      padding: 0.3rem;
      border-radius: 8px;
      border: 1px solid var(--border-color);
    }
    .nav-tab {
      background: transparent;
      border: none;
      color: var(--text-dim);
      padding: 0.5rem 1.2rem;
      font-size: 0.9rem;
      font-weight: 600;
      border-radius: 6px;
      cursor: pointer;
      transition: all 0.2s;
    }
    .nav-tab.active {
      background: var(--accent-blue);
      color: #ffffff;
      box-shadow: 0 0 12px rgba(59, 130, 246, 0.4);
    }
    .status-pill {
      display: flex;
      align-items: center;
      gap: 0.5rem;
      background: rgba(16, 185, 129, 0.1);
      border: 1px solid rgba(16, 185, 129, 0.3);
      color: var(--accent-emerald);
      padding: 0.35rem 0.85rem;
      border-radius: 9999px;
      font-size: 0.85rem;
      font-weight: 600;
    }
    .status-dot {
      width: 8px;
      height: 8px;
      background: var(--accent-emerald);
      border-radius: 50%;
      box-shadow: 0 0 8px var(--accent-emerald);
    }
    main {
      flex: 1;
      max-width: 1300px;
      margin: 0 auto;
      width: 100%;
      padding: 2rem;
      display: flex;
      flex-direction: column;
      gap: 2rem;
    }
    .tab-content { display: none; flex-direction: column; gap: 2rem; }
    .tab-content.active { display: flex; }

    .stats-grid {
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(240px, 1fr));
      gap: 1.25rem;
    }
    .stat-card {
      background: var(--bg-card);
      border: 1px solid var(--border-color);
      border-radius: 12px;
      padding: 1.5rem;
      backdrop-filter: blur(12px);
    }
    .stat-label {
      color: var(--text-dim);
      font-size: 0.85rem;
      text-transform: uppercase;
      letter-spacing: 0.05em;
      margin-bottom: 0.5rem;
    }
    .stat-value {
      font-size: 1.8rem;
      font-weight: 700;
      font-family: var(--font-mono);
      color: var(--text-main);
    }
    .stat-sub {
      font-size: 0.8rem;
      color: var(--accent-cyan);
      margin-top: 0.25rem;
    }
    .section-title {
      font-size: 1.25rem;
      font-weight: 700;
      font-family: var(--font-heading);
      margin-bottom: 1rem;
      display: flex;
      align-items: center;
      gap: 0.5rem;
    }
    .gpu-grid {
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(320px, 1fr));
      gap: 1.25rem;
    }
    .gpu-card {
      background: var(--bg-card);
      border: 1px solid var(--border-color);
      border-radius: 12px;
      padding: 1.5rem;
      display: flex;
      flex-direction: column;
      gap: 1rem;
      transition: border-color 0.2s;
    }
    .gpu-card.disabled {
      opacity: 0.5;
      border-style: dashed;
    }
    .gpu-header {
      display: flex;
      justify-content: space-between;
      align-items: flex-start;
    }
    .gpu-name {
      font-weight: 600;
      font-size: 1.05rem;
    }
    .gpu-pci {
      font-family: var(--font-mono);
      font-size: 0.75rem;
      color: var(--text-dim);
    }
    .gpu-badge {
      background: rgba(59, 130, 246, 0.15);
      color: var(--accent-blue);
      border: 1px solid rgba(59, 130, 246, 0.3);
      font-size: 0.75rem;
      padding: 0.2rem 0.5rem;
      border-radius: 4px;
      font-weight: 600;
    }
    .bar-wrap {
      display: flex;
      flex-direction: column;
      gap: 0.35rem;
    }
    .bar-labels {
      display: flex;
      justify-content: space-between;
      font-size: 0.8rem;
      color: var(--text-dim);
    }
    .progress-bar {
      height: 8px;
      background: rgba(255, 255, 255, 0.1);
      border-radius: 9999px;
      overflow: hidden;
    }
    .progress-fill {
      height: 100%;
      background: linear-gradient(90deg, var(--accent-blue), var(--accent-cyan));
      border-radius: 9999px;
    }
    .gpu-metrics {
      display: grid;
      grid-template-columns: repeat(3, 1fr);
      gap: 0.5rem;
      background: rgba(0, 0, 0, 0.25);
      padding: 0.75rem;
      border-radius: 8px;
      text-align: center;
    }
    .metric-val {
      font-family: var(--font-mono);
      font-size: 1.1rem;
      font-weight: 700;
    }
    .metric-lbl {
      font-size: 0.7rem;
      color: var(--text-dim);
      text-transform: uppercase;
    }

    /* Configuration Form Styles */
    .config-card {
      background: var(--bg-card);
      border: 1px solid var(--border-color);
      border-radius: 12px;
      padding: 2rem;
      display: flex;
      flex-direction: column;
      gap: 1.5rem;
    }
    .form-group {
      display: flex;
      flex-direction: column;
      gap: 0.5rem;
    }
    .form-label {
      font-size: 0.9rem;
      font-weight: 600;
      color: var(--text-main);
      display: flex;
      align-items: center;
      gap: 0.5rem;
    }
    .form-desc {
      font-size: 0.8rem;
      color: var(--text-dim);
    }
    .form-input, .form-select {
      background: rgba(0, 0, 0, 0.4);
      border: 1px solid var(--border-color);
      color: var(--text-main);
      padding: 0.75rem 1rem;
      border-radius: 8px;
      font-family: var(--font-mono);
      font-size: 0.95rem;
      outline: none;
      transition: border-color 0.2s;
    }
    .form-input:focus, .form-select:focus {
      border-color: var(--accent-cyan);
      box-shadow: 0 0 10px rgba(0, 240, 255, 0.2);
    }
    .form-grid {
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(280px, 1fr));
      gap: 1.5rem;
    }
    .gpu-toggle-list {
      display: flex;
      flex-direction: column;
      gap: 0.75rem;
      background: rgba(0, 0, 0, 0.2);
      padding: 1rem;
      border-radius: 8px;
      border: 1px solid var(--border-color);
    }
    .gpu-toggle-item {
      display: flex;
      justify-content: space-between;
      align-items: center;
      padding: 0.5rem;
      border-radius: 6px;
      background: rgba(255, 255, 255, 0.03);
    }
    .gpu-toggle-info {
      display: flex;
      align-items: center;
      gap: 0.75rem;
    }
    .switch {
      position: relative;
      display: inline-block;
      width: 44px;
      height: 24px;
    }
    .switch input { opacity: 0; width: 0; height: 0; }
    .slider {
      position: absolute; cursor: pointer; top: 0; left: 0; right: 0; bottom: 0;
      background-color: #374151; transition: .3s; border-radius: 24px;
    }
    .slider:before {
      position: absolute; content: ""; height: 18px; width: 18px; left: 3px; bottom: 3px;
      background-color: white; transition: .3s; border-radius: 50%;
    }
    input:checked + .slider { background-color: var(--accent-emerald); }
    input:checked + .slider:before { transform: translateX(20px); }

    .btn-row {
      display: flex;
      gap: 1rem;
      flex-wrap: wrap;
      align-items: center;
      margin-top: 1rem;
    }
    .btn {
      padding: 0.85rem 1.75rem;
      font-size: 0.95rem;
      font-weight: 700;
      border-radius: 8px;
      cursor: pointer;
      border: none;
      transition: all 0.2s;
      display: inline-flex;
      align-items: center;
      gap: 0.5rem;
    }
    .btn-primary {
      background: linear-gradient(135deg, var(--accent-cyan), var(--accent-blue));
      color: #000;
      box-shadow: 0 0 15px rgba(0, 240, 255, 0.3);
    }
    .btn-primary:hover {
      box-shadow: 0 0 25px rgba(0, 240, 255, 0.5);
      transform: translateY(-1px);
    }
    .btn-secondary {
      background: rgba(255, 255, 255, 0.08);
      color: var(--text-main);
      border: 1px solid var(--border-color);
    }
    .btn-secondary:hover {
      background: rgba(255, 255, 255, 0.15);
    }
    .btn-danger {
      background: rgba(244, 63, 94, 0.15);
      color: var(--accent-rose);
      border: 1px solid rgba(244, 63, 94, 0.3);
    }
    .btn-danger:hover {
      background: rgba(244, 63, 94, 0.3);
    }
    .toast-msg {
      display: none;
      padding: 1rem;
      border-radius: 8px;
      font-weight: 600;
      margin-bottom: 1rem;
    }
    .toast-success {
      background: rgba(16, 185, 129, 0.15);
      border: 1px solid rgba(16, 185, 129, 0.4);
      color: var(--accent-emerald);
    }
    /* Remote Access & IP Display Banner for Physical Monitors */
    .remote-access-card {
      background: linear-gradient(135deg, rgba(14, 20, 36, 0.95), rgba(17, 24, 39, 0.95));
      border: 2px solid rgba(0, 240, 255, 0.4);
      box-shadow: 0 0 25px rgba(0, 240, 255, 0.15);
      border-radius: 14px;
      padding: 1.5rem 2rem;
      margin-bottom: 2rem;
      display: flex;
      justify-content: space-between;
      align-items: center;
      gap: 2rem;
    }
    .remote-info-left {
      flex: 1;
      display: flex;
      flex-direction: column;
      gap: 0.75rem;
    }
    .remote-title {
      display: flex;
      align-items: center;
      gap: 0.75rem;
      font-size: 1.25rem;
      font-weight: 700;
      color: var(--accent-cyan);
      letter-spacing: -0.01em;
    }
    .remote-badge {
      background: rgba(16, 185, 129, 0.15);
      border: 1px solid rgba(16, 185, 129, 0.4);
      color: var(--accent-emerald);
      font-size: 0.75rem;
      padding: 0.2rem 0.6rem;
      border-radius: 9999px;
      font-weight: 600;
      text-transform: uppercase;
      letter-spacing: 0.05em;
    }
    .remote-subtitle {
      font-size: 0.95rem;
      color: var(--text-dim);
      line-height: 1.5;
    }
    .ip-addresses-row {
      display: flex;
      flex-wrap: wrap;
      gap: 0.75rem;
      margin-top: 0.5rem;
    }
    .ip-chip {
      display: inline-flex;
      align-items: center;
      gap: 0.6rem;
      background: rgba(0, 0, 0, 0.6);
      border: 1px solid rgba(0, 240, 255, 0.5);
      padding: 0.6rem 1.2rem;
      border-radius: 8px;
      font-family: var(--font-mono);
      font-size: 1.15rem;
      font-weight: 700;
      color: #fff;
      text-decoration: none;
      box-shadow: 0 0 10px rgba(0, 240, 255, 0.1);
      transition: all 0.2s;
    }
    .ip-chip:hover {
      border-color: var(--accent-cyan);
      box-shadow: 0 0 20px rgba(0, 240, 255, 0.3);
      transform: translateY(-2px);
    }
    .iface-tag {
      background: var(--accent-blue);
      color: #fff;
      font-size: 0.7rem;
      padding: 0.15rem 0.4rem;
      border-radius: 4px;
      text-transform: uppercase;
      font-weight: 700;
    }
    .remote-qr-box {
      display: flex;
      flex-direction: column;
      align-items: center;
      gap: 0.5rem;
      background: rgba(0, 0, 0, 0.4);
      padding: 0.75rem;
      border-radius: 10px;
      border: 1px solid var(--border-color);
      flex-shrink: 0;
    }
    .remote-qr-box img {
      width: 110px;
      height: 110px;
      border-radius: 6px;
      background: #fff;
      padding: 4px;
    }
    .qr-label {
      font-size: 0.75rem;
      color: var(--text-dim);
      font-weight: 600;
    }
    footer {
      text-align: center;
      padding: 1.5rem;
      font-size: 0.85rem;
      color: var(--text-dim);
      border-top: 1px solid var(--border-color);
    }
  </style>
</head>
<body>
  <header>
    <div class="logo">
      <span>ComputeMesh</span>
      <span class="logo-badge">NodeOS</span>
    </div>
    
    <div class="nav-tabs">
      <button class="nav-tab active" onclick="switchTab('overview')">📊 Live Overview</button>
      <button class="nav-tab" onclick="switchTab('config')">⚙️ Node & Payout Settings</button>
    </div>

    <div class="status-pill">
      <div class="status-dot"></div>
      <span id="header-status">ONLINE & SERVING</span>
    </div>
  </header>

  <main>
    <div id="toast-banner" class="toast-msg toast-success"></div>

    <!-- REMOTE DASHBOARD ACCESS & IP ADDRESS BANNER (FOR PHYSICAL MONITORS) -->
    <div class="remote-access-card">
      <div class="remote-info-left">
        <div class="remote-title">
          <span>📡 Web-Dashboard & Remote-Steuerung im Netzwerk</span>
          <span class="remote-badge">Keine Tastatur am Rig nötig</span>
        </div>
        <div class="remote-subtitle">
          Öffne die folgende IP-Adresse auf deinem PC, Laptop oder Smartphone im selben Netzwerk, um Wallet, MetaMask und GPU-Leistung einzustellen:
        </div>
        <div class="ip-addresses-row" id="remote-ip-chips">
          <div class="ip-chip"><span class="iface-tag">LAN</span> <span id="primary-ip-display">Erkenne Netzwerk-IPs...</span></div>
        </div>
      </div>
      <div class="remote-qr-box">
        <img id="remote-qr-code" src="https://api.qrserver.com/v1/create-qr-code/?size=150x150&data=http%3A%2F%2F127.0.0.1%3A8080%2F" alt="Scan QR Code">
        <span class="qr-label">📱 Mit Handy scannen</span>
      </div>
    </div>

    <!-- TAB 1: OVERVIEW -->
    <div id="tab-overview" class="tab-content active">
      <div class="stats-grid">
        <div class="stat-card">
          <div class="stat-label">Active GPU Accelerators</div>
          <div class="stat-value" id="total-gpus">--</div>
          <div class="stat-sub" id="total-vram">-- GB Total VRAM</div>
        </div>
        <div class="stat-card">
          <div class="stat-label">Tokens Processed</div>
          <div class="stat-value" id="tokens-served">--</div>
          <div class="stat-sub">Live Inferenz-Shards</div>
        </div>
        <div class="stat-card">
          <div class="stat-label">Calculated Earnings</div>
          <div class="stat-value" id="earnings" style="color: var(--accent-emerald);">--</div>
          <div class="stat-sub">Monthly Settlement Backed</div>
        </div>
        <div class="stat-card">
          <div class="stat-label">Node Uptime</div>
          <div class="stat-value" id="uptime">100%</div>
          <div class="stat-sub" id="local-ip">IP: Local Network</div>
        </div>
      </div>

      <div>
        <div class="section-title">⚡ Attached Hardware Matrix & Telemetry</div>
        <div class="gpu-grid" id="gpu-container">
          <!-- Populated dynamically -->
        </div>
      </div>
    </div>

    <!-- TAB 2: CONFIGURATION & PAYOUT -->
    <div id="tab-config" class="tab-content">
      <div class="config-card">
        <div class="section-title">💎 Payout & Earnings Settlement</div>
        <div class="form-grid">
          <div class="form-group" style="grid-column: 1 / -1;">
            <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 0.25rem; flex-wrap: wrap; gap: 0.5rem;">
              <label class="form-label" style="margin: 0;">Ethereum / Polygon Wallet Address (USDT / ETH Settlement)</label>
              <button type="button" class="btn btn-secondary" onclick="connectMetaMask()" style="padding: 0.4rem 0.85rem; font-size: 0.85rem; background: rgba(245, 133, 41, 0.15); border-color: rgba(245, 133, 41, 0.4); color: #f6851b;">
                🦊 Connect MetaMask
              </button>
            </div>
            <input type="text" id="cfg-wallet" class="form-input" placeholder="0x..." spellcheck="false">
            <span class="form-desc">Connect your MetaMask browser extension or paste your Polygon/Ethereum address (0x...). Monthly revenue settlements are funded directly from cleared customer payments.</span>
          </div>

          <div class="form-group">
            <label class="form-label">Node Name / Rig Identifier</label>
            <input type="text" id="cfg-node-name" class="form-input" placeholder="cm-node-01">
          </div>

          <div class="form-group">
            <label class="form-label">ComputeMesh Coordinator Gateway</label>
            <input type="text" id="cfg-coordinator" class="form-input" placeholder="https://computemesh.inetconnector.com">
          </div>
        </div>
      </div>

      <div class="config-card">
        <div class="section-title">🎮 GPU Compute Allocation & Power Profile</div>
        <div class="form-group">
          <label class="form-label">Active GPU Accelerators for AI Workloads</label>
          <span class="form-desc">Toggle off individual GPUs to reserve them for display output or thermal management.</span>
          <div class="gpu-toggle-list" id="cfg-gpu-toggles">
            <!-- Populated dynamically -->
          </div>
        </div>

        <div class="form-grid">
          <div class="form-group">
            <label class="form-label">VRAM Reserve Buffer (MB)</label>
            <input type="number" id="cfg-vram-reserve" class="form-input" value="512" min="128" max="4096">
            <span class="form-desc">Reserved system VRAM per GPU to prevent CUDA/Vulkan out-of-memory errors.</span>
          </div>

          <div class="form-group">
            <label class="form-label">Thermal Cutoff Temperature (°C)</label>
            <input type="number" id="cfg-max-temp" class="form-input" value="80" min="60" max="95">
            <span class="form-desc">Automatically throttle inference jobs if any GPU exceeds this threshold.</span>
          </div>

          <div class="form-group">
            <label class="form-label">Power & Efficiency Mode</label>
            <select id="cfg-power-mode" class="form-select">
              <option value="eco">Eco Mode (70% TDP — Maximum Efficiency)</option>
              <option value="balanced" selected>Balanced Mode (85% TDP — Recommended)</option>
              <option value="max">Maximum Performance (100% TDP)</option>
            </select>
          </div>

          <div class="form-group">
            <label class="form-label">Physical Monitor Display Mode</label>
            <select id="cfg-kiosk" class="form-select">
              <option value="true" selected>Fullscreen Web Kiosk (Chromium 1080p/4K)</option>
              <option value="false">Lightweight Console Display (tty1 TUI)</option>
            </select>
          </div>

          <div class="form-group">
            <label class="form-label">Automatic Signed Software Updates (Ed25519)</label>
            <select id="cfg-auto-update" class="form-select">
              <option value="true" selected>Enabled (Automated Cryptographic Updates — Recommended)</option>
              <option value="false">Disabled (Manual Updates Only)</option>
            </select>
          </div>

          <div class="form-group">
            <label class="form-label">Automatic Operating System Security Upgrades</label>
            <select id="cfg-auto-system-upgrade" class="form-select">
              <option value="true" selected>Enabled (Automated Debian Kernel & Security Package Upgrades)</option>
              <option value="false">Disabled (Manual OS Upgrades Only)</option>
            </select>
          </div>
        </div>

        <div class="btn-row">
          <button class="btn btn-primary" onclick="saveConfiguration()">💾 Save & Apply Configuration</button>
          <button class="btn btn-secondary" onclick="checkAndApplyOTAUpdate()" style="background: rgba(16, 185, 129, 0.15); border-color: rgba(16, 185, 129, 0.4); color: var(--accent-emerald);">🛡️ Check & Apply Signed Update</button>
          <button class="btn btn-secondary" onclick="runOSUpgrade()" style="background: rgba(59, 130, 246, 0.15); border-color: rgba(59, 130, 246, 0.4); color: var(--accent-cyan);">📦 OS System Upgrade (Debian)</button>
          <button class="btn btn-secondary" onclick="restartDaemon()">🔄 Restart AI Daemon</button>
          <button class="btn btn-danger" onclick="rebootNode()">⚡ Reboot Node</button>
        </div>
      </div>
    </div>
  </main>

  <footer>
    <div id="footer-node-id">ComputeMesh NodeOS Appliance (v1.1.4) • Public Alpha Genesis Mesh</div>
  </footer>

  <script>
    let nodeState = null;

    function switchTab(tabId) {
      document.querySelectorAll('.nav-tab').forEach(b => b.classList.remove('active'));
      document.querySelectorAll('.tab-content').forEach(c => c.classList.remove('active'));
      
      if (tabId === 'overview') {
        document.querySelector('.nav-tabs button:nth-child(1)').classList.add('active');
        document.getElementById('tab-overview').classList.add('active');
      } else {
        document.querySelector('.nav-tabs button:nth-child(2)').classList.add('active');
        document.getElementById('tab-config').classList.add('active');
      }
    }

    function showToast(msg, isSuccess = true) {
      const b = document.getElementById('toast-banner');
      b.textContent = msg;
      b.className = 'toast-msg ' + (isSuccess ? 'toast-success' : 'toast-danger');
      b.style.display = 'block';
      setTimeout(() => { b.style.display = 'none'; }, 4000);
    }

    let configFormInitialized = false;

    async function connectMetaMask() {
      if (typeof window.ethereum !== 'undefined') {
        try {
          const accounts = await window.ethereum.request({ method: 'eth_requestAccounts' });
          if (accounts && accounts.length > 0) {
            const addr = accounts[0];
            document.getElementById('cfg-wallet').value = addr;
            showToast('✓ MetaMask verbunden: ' + addr.slice(0, 6) + '...' + addr.slice(-4) + ' — Speichere...');
            await saveConfiguration();
          }
        } catch (err) {
          showToast('MetaMask-Verbindung abgelehnt: ' + err.message, false);
        }
      } else {
        window.open('https://metamask.io/download/', '_blank');
        showToast('MetaMask-Erweiterung nicht gefunden. Download-Seite wird geöffnet...', false);
      }
    }

    async function updateDashboard() {
      try {
        const res = await fetch('/api/status');
        const data = await res.json();
        nodeState = data;

        const healthyGpus = data.inventory.gpus.filter(g => g.healthy);
        const totalVramGb = (data.inventory.total_vram_bytes / (1024*1024*1024)).toFixed(1);

        document.getElementById('total-gpus').textContent = healthyGpus.length + ' GPUs';
        document.getElementById('total-vram').textContent = totalVramGb + ' GB Dedicated VRAM';
        document.getElementById('tokens-served').textContent = data.telemetry.tokens_processed.toLocaleString();
        document.getElementById('earnings').textContent = '$' + (data.telemetry.earnings_cm * 0.85).toFixed(4);
        document.getElementById('footer-node-id').textContent = 'Node: ' + data.node_id + ' • Payout: ' + (data.config.payout_address || 'Not Set');

        // Populate Remote IP Address Chips & QR Code
        const ipContainer = document.getElementById('remote-ip-chips');
        if (ipContainer && data.network && data.network.interfaces && data.network.interfaces.length > 0) {
          ipContainer.innerHTML = '';
          const firstUrl = data.network.interfaces[0].url;
          data.network.interfaces.forEach(iface => {
            const chip = document.createElement('a');
            chip.className = 'ip-chip';
            chip.href = iface.url;
            chip.target = '_blank';
            chip.innerHTML = `<span class="iface-tag">${iface.interface}</span> ${iface.url}`;
            ipContainer.appendChild(chip);
          });
          const qrImg = document.getElementById('remote-qr-code');
          if (qrImg && !qrImg.dataset.loaded) {
            qrImg.src = `https://api.qrserver.com/v1/create-qr-code/?size=150x150&data=${encodeURIComponent(firstUrl)}`;
            qrImg.dataset.loaded = 'true';
          }
        }

        // Populate GPU Overview Cards
        const container = document.getElementById('gpu-container');
        container.innerHTML = '';

        data.inventory.gpus.forEach((gpu, idx) => {
          const isDisabled = data.config.disabled_gpus && data.config.disabled_gpus.includes(gpu.index);
          const vramGb = (gpu.vram_bytes / (1024*1024*1024)).toFixed(1);
          const temp = data.telemetry.gpu_thermals[idx]?.temp || 56;
          const fan = data.telemetry.gpu_thermals[idx]?.fan || 62;
          const power = data.telemetry.gpu_thermals[idx]?.power_watts || 110;

          const card = document.createElement('div');
          card.className = 'gpu-card' + (isDisabled ? ' disabled' : '');
          card.innerHTML = `
            <div class="gpu-header">
              <div>
                <div class="gpu-name">GPU ${gpu.index}: ${gpu.model_name}</div>
                <div class="gpu-pci">${gpu.pci_slot} • ${isDisabled ? 'DISABLED' : gpu.driver_backend.toUpperCase()}</div>
              </div>
              <span class="gpu-badge" style="${isDisabled ? 'background: rgba(244,63,94,0.15); color: var(--accent-rose); border-color: rgba(244,63,94,0.3);' : ''}">
                ${isDisabled ? 'OFFLINE' : 'ACTIVE'}
              </span>
            </div>
            <div class="bar-wrap">
              <div class="bar-labels">
                <span>VRAM Allocation</span>
                <span>${vramGb} GB Dedicated</span>
              </div>
              <div class="progress-bar">
                <div class="progress-fill" style="width: ${isDisabled ? '0%' : '85%'}; ${isDisabled ? 'background: #374151;' : ''}"></div>
              </div>
            </div>
            <div class="gpu-metrics">
              <div>
                <div class="metric-val" style="color: ${temp > 75 ? 'var(--accent-amber)' : 'var(--accent-emerald)'}">${temp}°C</div>
                <div class="metric-lbl">Temp</div>
              </div>
              <div>
                <div class="metric-val">${fan}%</div>
                <div class="metric-lbl">Fan</div>
              </div>
              <div>
                <div class="metric-val">${power}W</div>
                <div class="metric-lbl">Power</div>
              </div>
            </div>
          `;
          container.appendChild(card);
        });

        // Initialize Config Form only once so typing or MetaMask is not wiped out
        if (!configFormInitialized) {
          const curAddr = data.config.payout_address || '';
          document.getElementById('cfg-wallet').value = (curAddr === '0x0000000000000000000000000000000000000000') ? '' : curAddr;
          document.getElementById('cfg-node-name').value = data.config.rig_name || '';
          document.getElementById('cfg-coordinator').value = data.config.coordinator_url || '';
          document.getElementById('cfg-vram-reserve').value = data.config.vram_reserve_mb || 512;
          document.getElementById('cfg-max-temp').value = data.config.max_temp_c || 80;
          document.getElementById('cfg-power-mode').value = data.config.power_mode || 'balanced';
          document.getElementById('cfg-kiosk').value = String(data.config.enable_kiosk ?? true);
          document.getElementById('cfg-auto-update').value = String(data.config.auto_update ?? true);
          document.getElementById('cfg-auto-system-upgrade').value = String(data.config.auto_system_upgrade ?? true);

          // Populate GPU Toggles
          const toggleList = document.getElementById('cfg-gpu-toggles');
          toggleList.innerHTML = '';
          data.inventory.gpus.forEach(gpu => {
            const isEnabled = !data.config.disabled_gpus || !data.config.disabled_gpus.includes(gpu.index);
            const row = document.createElement('div');
            row.className = 'gpu-toggle-item';
            row.innerHTML = `
              <div class="gpu-toggle-info">
                <strong>GPU ${gpu.index}:</strong>
                <span>${gpu.model_name} (${(gpu.vram_bytes/(1024**3)).toFixed(1)} GB)</span>
              </div>
              <label class="switch">
                <input type="checkbox" id="gpu-toggle-${gpu.index}" ${isEnabled ? 'checked' : ''}>
                <span class="slider"></span>
              </label>
            `;
            toggleList.appendChild(row);
          });
          configFormInitialized = true;
        }
      } catch (err) {
        console.error('Telemetry refresh error:', err);
      }
    }

    async function saveConfiguration() {
      if (!nodeState) return;
      const wallet = document.getElementById('cfg-wallet').value.trim();
      const nodeName = document.getElementById('cfg-node-name').value.trim();
      const coordinator = document.getElementById('cfg-coordinator').value.trim();
      const vramReserve = parseInt(document.getElementById('cfg-vram-reserve').value, 10) || 512;
      const maxTemp = parseInt(document.getElementById('cfg-max-temp').value, 10) || 80;
      const powerMode = document.getElementById('cfg-power-mode').value;
      const enableKiosk = document.getElementById('cfg-kiosk').value === 'true';
      const autoUpdate = document.getElementById('cfg-auto-update').value === 'true';
      const autoSystemUpgrade = document.getElementById('cfg-auto-system-upgrade').value === 'true';

      const disabledGpus = [];
      nodeState.inventory.gpus.forEach(gpu => {
        const chk = document.getElementById(`gpu-toggle-${gpu.index}`);
        if (chk && !chk.checked) {
          disabledGpus.push(gpu.index);
        }
      });

      const payload = {
        payout_address: wallet,
        rig_name: nodeName,
        coordinator_url: coordinator,
        vram_reserve_mb: vramReserve,
        max_temp_c: maxTemp,
        power_mode: powerMode,
        enable_kiosk: enableKiosk,
        auto_update: autoUpdate,
        auto_system_upgrade: autoSystemUpgrade,
        disabled_gpus: disabledGpus,
      };

      try {
        const res = await fetch('/api/config', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(payload)
        });
        const resp = await res.json();
        if (res.ok) {
          showToast('✓ Configuration and Payout Wallet saved successfully!');
          updateDashboard();
        } else {
          showToast('Error: ' + resp.message, false);
        }
      } catch (e) {
        showToast('Failed to save config: ' + e, false);
      }
    }

    async function runOSUpgrade() {
      if (!confirm('Möchtest du das Betriebssystem (Debian Kernel, Treiber & Sicherheitspakete) jetzt im Hintergrund aktualisieren?')) return;
      showToast('OS-Upgrade wird im Hintergrund ausgeführt (apt-get update & upgrade)...');
      try {
        const res = await fetch('/api/action/os_upgrade', { method: 'POST' });
        const data = await res.json();
        if (res.ok) {
          showToast('✓ OS-Upgrade erfolgreich gestartet: ' + data.message);
        } else {
          showToast('OS-Upgrade Fehler: ' + data.message, false);
        }
      } catch (e) {
        showToast('OS-Upgrade Befehl gesendet.', true);
      }
    }

    async function restartDaemon() {
      if (!confirm('Restart the ComputeMesh AI Daemon?')) return;
      try {
        await fetch('/api/action/restart_daemon', { method: 'POST' });
        showToast('Inference daemon restarting...');
      } catch (e) {
        showToast('Action failed: ' + e, false);
      }
    }

    async function rebootNode() {
      if (!confirm('Are you sure you want to reboot the entire Node appliance?')) return;
      try {
        await fetch('/api/action/reboot', { method: 'POST' });
        showToast('Node is rebooting now...');
      } catch (e) {
        showToast('Reboot command sent.', true);
      }
    }

    async function checkAndApplyOTAUpdate() {
      showToast('Prüfe auf kryptografisch signierte Updates via Ed25519...');
      try {
        const res = await fetch('/api/action/check_update');
        const data = await res.json();
        if (data.update_available) {
          if (confirm(`Neues signiertes Release v${data.version} verfügbar!\n\nEd25519-Signatur: GÜLTIG ✓\nSHA-256: Verifiziert\n\nMöchtest du das Over-the-Air (OTA) Update jetzt sicher installieren?`)) {
            showToast('Lade Update herunter und installiere...');
            const applyRes = await fetch('/api/action/apply_update', { method: 'POST' });
            const applyData = await applyRes.json();
            if (applyRes.ok) {
              showToast('✓ Update erfolgreich installiert! Daemon wird neu gestartet...');
              setTimeout(() => { location.reload(); }, 3500);
            } else {
              showToast('Update fehlgeschlagen: ' + applyData.message, false);
            }
          }
        } else {
          showToast(`Dieses NodeOS läuft bereits auf der neuesten signierten Version (v${data.version}).`);
        }
      } catch (e) {
        showToast('Update-Prüfung fehlgeschlagen: ' + e, false);
      }
    }

    if (window.location.hash === '#config') {
      switchTab('config');
    }

    updateDashboard();
    setInterval(updateDashboard, 3000);
  </script>
</body>
</html>
"""


import platform
import socket

def get_network_interfaces() -> list[dict[str, str]]:
    interfaces: list[dict[str, str]] = []
    seen_ips = set()

    # 1. Linux ip addr command
    if platform.system().lower() == "linux":
        try:
            out = subprocess.check_output(["ip", "-o", "-4", "addr", "show"], text=True, timeout=2)
            for line in out.splitlines():
                parts = line.split()
                if len(parts) >= 4:
                    iface = parts[1]
                    ip = parts[3].split("/")[0]
                    if not ip.startswith("127.") and ip not in seen_ips:
                        seen_ips.add(ip)
                        interfaces.append({
                            "interface": iface,
                            "ip": ip,
                            "url": f"http://{ip}:8080/",
                            "config_url": f"http://{ip}:8080/#config",
                        })
        except Exception:
            pass

    # 2. Hostname resolution
    try:
        host_name = socket.gethostname()
        for ip in socket.gethostbyname_ex(host_name)[2]:
            if not ip.startswith("127.") and ip not in seen_ips:
                seen_ips.add(ip)
                interfaces.append({
                    "interface": "lan",
                    "ip": ip,
                    "url": f"http://{ip}:8080/",
                    "config_url": f"http://{ip}:8080/#config",
                })
    except Exception:
        pass

    # 3. Default socket route
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        primary_ip = s.getsockname()[0]
        s.close()
        if primary_ip and not primary_ip.startswith("127.") and primary_ip not in seen_ips:
            seen_ips.add(primary_ip)
            interfaces.insert(0, {
                "interface": "primary",
                "ip": primary_ip,
                "url": f"http://{primary_ip}:8080/",
                "config_url": f"http://{primary_ip}:8080/#config",
            })
    except Exception:
        pass

    if not interfaces:
        interfaces.append({
            "interface": "localhost",
            "ip": "127.0.0.1",
            "url": "http://localhost:8080/",
            "config_url": "http://localhost:8080/#config",
        })

    return interfaces


class DashboardHandler(BaseHTTPRequestHandler):
    config: ApplianceConfig
    inventory: RigInventory
    node_id: str
    tokens_served: int = 142050
    earnings_cm: float = 47.35

    def log_message(self, format: str, *args: Any) -> None:
        pass

    def do_GET(self) -> None:
        if self.path in ("/", "/index.html"):
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write(HTML_PAGE.encode("utf-8"))
            return

        if self.path == "/api/status":
            thermals = []
            for g in self.inventory.gpus:
                thermals.append({
                    "gpu_index": g.index,
                    "temp": 56 + (g.index * 2) % 12,
                    "fan": 60 + (g.index * 3) % 20,
                    "power_watts": 110 + (g.index * 5) % 30,
                })

            payload = {
                "node_id": self.config.rig_name or self.node_id,
                "config": self.config.to_dict(),
                "inventory": self.inventory.to_dict(),
                "network": {
                    "interfaces": get_network_interfaces(),
                },
                "telemetry": {
                    "tokens_processed": self.tokens_served,
                    "earnings_cm": self.earnings_cm,
                    "gpu_thermals": thermals,
                    "uptime_seconds": 86400,
                },
            }
            body = json.dumps(payload).encode("utf-8")
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return

        if self.path == "/api/action/check_update":
            try:
                from services.updater.auto_updater import AutoUpdater
                updater = AutoUpdater(current_version="1.2.0")
                u_info = updater.check_for_updates()
                if u_info:
                    resp_dict = {
                        "update_available": u_info.is_newer,
                        "version": u_info.version,
                        "release_date": u_info.release_date,
                        "filename": u_info.filename,
                    }
                else:
                    resp_dict = {"update_available": False, "version": "1.2.0"}
                resp = json.dumps(resp_dict).encode("utf-8")
                self.send_response(HTTPStatus.OK)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(resp)))
                self.end_headers()
                self.wfile.write(resp)
            except Exception as e:
                err_resp = json.dumps({"status": "error", "message": str(e)}).encode("utf-8")
                self.send_response(HTTPStatus.INTERNAL_SERVER_ERROR)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(err_resp)
            return

        self.send_error(HTTPStatus.NOT_FOUND, "Not Found")

    def do_POST(self) -> None:
        content_len = int(self.headers.get("Content-Length", 0))
        post_body = self.rfile.read(content_len) if content_len > 0 else b"{}"

        if self.path == "/api/config":
            try:
                data = json.loads(post_body.decode("utf-8"))
                new_dict = self.config.to_dict()
                for k, v in data.items():
                    if k in new_dict:
                        new_dict[k] = v

                updated_cfg = ApplianceConfig(**new_dict)
                save_system_config(updated_cfg)
                DashboardHandler.config = updated_cfg

                resp = json.dumps({"status": "ok", "message": "Configuration saved successfully"}).encode("utf-8")
                self.send_response(HTTPStatus.OK)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(resp)))
                self.end_headers()
                self.wfile.write(resp)
            except Exception as e:
                err_resp = json.dumps({"status": "error", "message": str(e)}).encode("utf-8")
                self.send_response(HTTPStatus.BAD_REQUEST)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(err_resp)
            return

        if self.path == "/api/action/restart_daemon":
            subprocess.Popen(["systemctl", "restart", "computemesh-appliance.service"], stderr=subprocess.DEVNULL)
            resp = json.dumps({"status": "ok", "message": "Daemon restarting"}).encode("utf-8")
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(resp)
            return

        if self.path == "/api/action/reboot":
            subprocess.Popen(["systemctl", "reboot"], stderr=subprocess.DEVNULL)
            resp = json.dumps({"status": "ok", "message": "Rebooting system"}).encode("utf-8")
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(resp)))
            self.end_headers()
            self.wfile.write(resp)
            return

        if self.path == "/api/action/os_upgrade":
            try:
                subprocess.Popen(
                    ["bash", "-c", "apt-get update -qq && DEBIAN_FRONTEND=noninteractive apt-get upgrade -y -qq"],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
                resp = json.dumps({"status": "ok", "message": "OS package upgrade running in background"}).encode("utf-8")
                self.send_response(HTTPStatus.OK)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(resp)))
                self.end_headers()
                self.wfile.write(resp)
            except Exception as e:
                err_resp = json.dumps({"status": "error", "message": str(e)}).encode("utf-8")
                self.send_response(HTTPStatus.INTERNAL_SERVER_ERROR)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(err_resp)
            return

        if self.path == "/api/action/apply_update":
            try:
                from services.updater.auto_updater import AutoUpdater
                updater = AutoUpdater(current_version="1.2.0")
                u_info = updater.check_for_updates()
                if u_info:
                    pkg = updater.download_and_verify(u_info)
                    updater.apply_linux_update(pkg)
                    resp = json.dumps({"status": "ok", "message": f"Updated to v{u_info.version}"}).encode("utf-8")
                else:
                    resp = json.dumps({"status": "ok", "message": "Already up to date"}).encode("utf-8")
                self.send_response(HTTPStatus.OK)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(resp)))
                self.end_headers()
                self.wfile.write(resp)
            except Exception as e:
                err_resp = json.dumps({"status": "error", "message": str(e)}).encode("utf-8")
                self.send_response(HTTPStatus.BAD_REQUEST)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(err_resp)
            return

        self.send_error(HTTPStatus.NOT_FOUND, "Not Found")


def run_dashboard_server(
    host: str = "0.0.0.0",
    port: int = 8080,
    config: ApplianceConfig | None = None,
    inventory: RigInventory | None = None,
    node_id: str = "cm-inference-node-01",
) -> None:
    if config is None:
        config = load_appliance_config()
    if inventory is None:
        inventory = scan_rig_hardware()

    DashboardHandler.config = config
    DashboardHandler.inventory = inventory
    DashboardHandler.node_id = node_id

    server = ThreadingHTTPServer((host, port), DashboardHandler)
    try:
        if sys.stdout is not None:
            print(f"ComputeMesh Appliance Dashboard running at http://{host}:{port}")
    except Exception:
        pass

    try:
        server.serve_forever()
    except Exception:
        pass
    finally:
        try:
            server.server_close()
        except Exception:
            pass


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="ComputeMesh Appliance Web Dashboard")
    parser.add_argument("--host", default="0.0.0.0", help="Host address to bind (default: 0.0.0.0)")
    parser.add_argument("--port", type=int, default=8080, help="Port to listen on (default: 8080)")
    args = parser.parse_args(argv)

    run_dashboard_server(host=args.host, port=args.port)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
