"""ComputeMesh Heterogeneous Cluster Mesh Telemetry Aggregator."""
from __future__ import annotations

from datetime import datetime, timezone
import json
import os
import socket
import threading
import time
from typing import Any
import urllib.request

from tools.appliance.hardware_detector import is_integrated_display_adapter


def _extract_discrete_gpu_signature(node_dict: dict[str, Any]) -> tuple[Any, ...]:
    """Generates a normalized tuple fingerprint of discrete GPUs on a node."""
    inv = node_dict.get("inventory", {})
    gpus = inv.get("gpus", [])
    discrete = []
    for g in gpus:
        v = str(g.get("vendor", "")).strip().lower()
        m = str(g.get("model_name", "")).strip()
        vr = int(g.get("vram_bytes", 0) or 0)
        if g.get("healthy", True) and not is_integrated_display_adapter(v, m):
            discrete.append((v, m, vr))
    if discrete:
        discrete.sort()
        return tuple(discrete)
    total_vr = int(inv.get("total_vram_bytes", 0) or 0)
    if total_vr > 0:
        return ("vram_only", total_vr)
    return ()


def _get_local_ip_set() -> set[str]:
    """Retrieves all local host IP addresses to prevent self-polling loops."""
    ips = {"127.0.0.1", "localhost", "0.0.0.0"}
    try:
        hostname = socket.gethostname()
        for ip in socket.gethostbyname_ex(hostname)[2]:
            if ip:
                ips.add(ip)
    except Exception:
        pass
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        primary = s.getsockname()[0]
        s.close()
        if primary:
            ips.add(primary)
    except Exception:
        pass
    return ips


class MeshRegistryAggregator:
    def __init__(self, known_peers: list[str] | None = None, *, autostart: bool = False) -> None:
        raw_peers = os.environ.get("COMPUTEMESH_CLUSTER_PEERS", "").strip()
        if raw_peers:
            self.known_peers = [p.strip() for p in raw_peers.split(",") if p.strip()]
        else:
            self.known_peers = ["http://192.168.1.35:8080", "http://192.168.1.27:8080"]
        self._peer_nodes: dict[str, dict[str, Any]] = {}
        self._lock = threading.Lock()
        self._running = False
        self._thread: threading.Thread | None = None
        if autostart:
            self.start()

    def start(self) -> None:
        if self._running:
            return
        self._running = True
        self._thread = threading.Thread(target=self._background_poller, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._running = False

    def _background_poller(self) -> None:
        while self._running:
            local_ips = _get_local_ip_set()
            local_nid = str(getattr(self, "_local_status", {}).get("node_id", "")).strip()
            local_sig = _extract_discrete_gpu_signature(getattr(self, "_local_status", {})) if hasattr(self, "_local_status") else ()
            now_ts = time.time()

            # 1. Direct LAN peer polling (excluding local machine IPs)
            for peer in self.known_peers:
                try:
                    # Skip polling if target IP belongs to this local host
                    peer_host = peer.split("://")[-1].split(":")[0].split("/")[0]
                    if peer_host in local_ips:
                        continue

                    url = peer.rstrip("/") + "/api/status"
                    req = urllib.request.Request(url, headers={"User-Agent": "ComputeMesh-Aggregator/1.2"})
                    with urllib.request.urlopen(req, timeout=1.5) as resp:
                        if resp.status == 200:
                            d = json.loads(resp.read().decode("utf-8"))
                            nid = str(d.get("node_id", peer)).strip()
                            peer_sig = _extract_discrete_gpu_signature(d)
                            # If peer is actually the local machine under another name, skip
                            if nid == local_nid or (local_sig and peer_sig == local_sig):
                                continue
                            with self._lock:
                                self._peer_nodes[nid] = {
                                    "node_id": nid,
                                    "status": "online",
                                    "inventory": d.get("inventory", {}),
                                    "telemetry": d.get("telemetry", {}),
                                    "last_seen": now_ts,
                                }
                except Exception:
                    pass

            # 2. Coordinator Fleet Sync via owner_key
            try:
                from tools.appliance.appliance_config import load_appliance_config
                from config import CONFIG
                cfg = load_appliance_config()
                owner_key = getattr(cfg, "owner_key", "")
                if owner_key:
                    fleet_url = f"{CONFIG.endpoints.base_url}/api/v1/mesh/fleet?owner_key={owner_key}"
                    req = urllib.request.Request(fleet_url, headers={"User-Agent": "ComputeMesh-Aggregator/1.2"})
                    with urllib.request.urlopen(req, timeout=3.0) as resp:
                        if resp.status == 200:
                            fleet_data = json.loads(resp.read().decode("utf-8"))
                            nodes = fleet_data.get("nodes", [])
                            for n in nodes:
                                nid = str(n.get("node_id", "")).strip()
                                if not nid or nid == local_nid or not n.get("is_online", False):
                                    continue
                                if nid in ("test-node-custom", "mifcom", "windows-laptop", "unnamed-node"):
                                    continue

                                gpus_list = n.get("gpus", [])
                                vram_total = int(float(n.get("vram_gb", 0) or 0) * (1024**3))
                                if not gpus_list and vram_total <= 0:
                                    continue

                                peer_dict = {
                                    "node_id": nid,
                                    "status": "online",
                                    "inventory": {
                                        "total_vram_bytes": vram_total,
                                        "gpus": [
                                            {
                                                "vendor": "nvidia" if "nvidia" in str(g).lower() else ("amd" if "amd" in str(g).lower() else "unknown"),
                                                "model_name": str(g),
                                                "vram_bytes": vram_total // max(1, len(gpus_list)),
                                                "healthy": True,
                                            }
                                            for g in gpus_list
                                        ],
                                    },
                                    "telemetry": {
                                        "local_compute_tflops": float(n.get("tflops", 0.0) or 0.0),
                                        "tokens_processed": 0,
                                    },
                                    "last_seen": now_ts,
                                }
                                peer_sig = _extract_discrete_gpu_signature(peer_dict)
                                if local_sig and peer_sig == local_sig:
                                    # Same hardware signature as local host — skip duplicate
                                    continue

                                with self._lock:
                                    self._peer_nodes[nid] = peer_dict
            except Exception:
                pass

            # 3. Evict stale peer entries not seen for > 20 seconds
            with self._lock:
                stale_keys = [
                    k for k, v in self._peer_nodes.items()
                    if now_ts - float(v.get("last_seen", 0) or 0) > 20.0
                ]
                for k in stale_keys:
                    self._peer_nodes.pop(k, None)

            time.sleep(5)

    def get_mesh_stats(self, local_status: dict[str, Any] | None = None) -> dict[str, Any]:
        if local_status:
            with self._lock:
                self._local_status = local_status

        nodes: list[dict[str, Any]] = []
        seen_signatures: set[tuple[Any, ...]] = set()
        seen_nids: set[str] = set()

        with self._lock:
            # 1. Authoritative local machine entry
            local_entry = local_status or getattr(self, "_local_status", None)
            if not local_entry:
                try:
                    from tools.appliance.hardware_detector import scan_rig_hardware
                    inv = scan_rig_hardware()
                    local_entry = {
                        "node_id": "windows-laptop",
                        "status": "online",
                        "inventory": inv.to_dict(),
                        "telemetry": {"tokens_processed": 0, "local_compute_tflops": 0.0},
                    }
                except Exception:
                    local_entry = None

            if local_entry:
                local_nid = str(local_entry.get("node_id", "")).strip()
                local_sig = _extract_discrete_gpu_signature(local_entry)
                nodes.append(local_entry)
                if local_nid:
                    seen_nids.add(local_nid)
                if local_sig:
                    seen_signatures.add(local_sig)

            # 2. Add peer nodes with strict single-unit hardware deduplication
            for peer_data in list(self._peer_nodes.values()):
                p_nid = str(peer_data.get("node_id", "")).strip()
                if not p_nid or p_nid in seen_nids:
                    continue
                if p_nid in ("test-node-custom", "mifcom", "windows-laptop", "unnamed-node"):
                    continue

                p_sig = _extract_discrete_gpu_signature(peer_data)
                if not p_sig:
                    # Node has no discrete GPUs or VRAM
                    continue
                if p_sig in seen_signatures:
                    # Exact same physical GPU hardware already represented in mesh
                    continue

                seen_nids.add(p_nid)
                seen_signatures.add(p_sig)
                nodes.append(peer_data)

        total_gpus = 0
        total_vram_bytes = 0
        total_tflops = 0.0
        total_tokens = 0
        node_details = []

        local_nid = str((local_status or getattr(self, "_local_status", {})).get("node_id", ""))

        for n in nodes:
            inv = n.get("inventory", {})
            tel = n.get("telemetry", {})
            gpus = inv.get("gpus", [])
            healthy_gpus = [
                g for g in gpus
                if g.get("healthy", True) and not is_integrated_display_adapter(g.get("vendor", "unknown"), g.get("model_name", ""))
            ]
            node_vram_bytes = sum(g.get("vram_bytes", 0) for g in healthy_gpus)
            if not healthy_gpus and inv.get("total_vram_bytes", 0) > 0 and not is_integrated_display_adapter("unknown", inv.get("host_architecture", "")):
                node_vram_bytes = inv.get("total_vram_bytes", 0)

            total_gpus += len(healthy_gpus)
            total_vram_bytes += node_vram_bytes

            # Calculate accurate TFLOPS per discrete GPU
            tf = 0.0
            for g in healthy_gpus:
                m_lower = str(g.get("model_name", "")).lower()
                if "4090" in m_lower:
                    tf += 82.6
                elif "3080" in m_lower or "3090" in m_lower:
                    tf += 24.0
                elif "mi25" in m_lower or "vega" in m_lower:
                    tf += 24.6
                elif "6800" in m_lower or "6900" in m_lower or "7900" in m_lower:
                    tf += 32.0
                elif "intel" in m_lower:
                    tf += 1.0
                else:
                    tf += round(max(1.0, (g.get("vram_bytes", 0) / (1024**3)) * 1.5), 1)

            if tf == 0.0:
                tf = tel.get("local_compute_tflops", 0.0) or (len(healthy_gpus) * 12.5)

            total_tflops += tf
            total_tokens += int(tel.get("tokens_processed", 0) or 0)

            current_nid = str(n.get("node_id", ""))
            is_local = (current_nid == local_nid) if (local_nid and current_nid) else False

            gpu_names = [f"{g.get('model_name', 'GPU')} ({round(g.get('vram_bytes', 0)/(1024**3), 1)} GB)" for g in healthy_gpus]
            gpu_summary = ", ".join(gpu_names) if gpu_names else f"{len(healthy_gpus)} GPU(s)"

            node_details.append({
                "node_id": current_nid or "unnamed-node",
                "is_local": is_local,
                "gpus_count": len(healthy_gpus),
                "gpu_summary": gpu_summary,
                "vram_gb": round(node_vram_bytes / (1024**3), 1),
                "tflops": round(tf, 1),
                "tokens": tel.get("tokens_processed", 0),
            })

        vram_gb = round(total_vram_bytes / (1024**3), 1)

        return {
            "source": "authenticated_registry",
            "total_nodes_online": len(nodes),
            "total_gpus_active": total_gpus,
            "total_vram_gb": vram_gb,
            "total_vram_bytes": total_vram_bytes,
            "total_compute_tflops": round(total_tflops, 1),
            "total_tokens_processed": total_tokens,
            "nodes": node_details,
            "timestamp": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        }


GLOBAL_MESH_AGGREGATOR = MeshRegistryAggregator(
    autostart=os.environ.get("COMPUTEMESH_AUTOSTART_MESH_POLLER", "1").strip().lower() not in ("0", "false", "no", "off")
)
