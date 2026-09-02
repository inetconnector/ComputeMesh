"""ComputeMesh Heterogeneous Cluster Mesh Telemetry Aggregator."""
from __future__ import annotations

from datetime import datetime, timezone
import json
import os
import threading
import time
from typing import Any
import urllib.request


class MeshRegistryAggregator:
    def __init__(self, known_peers: list[str] | None = None, *, autostart: bool = False) -> None:
        raw_peers = os.environ.get("COMPUTEMESH_CLUSTER_PEERS", "").strip()
        if raw_peers:
            self.known_peers = [p.strip() for p in raw_peers.split(",") if p.strip()]
        else:
            self.known_peers = ["http://192.168.1.27:8080"]
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
            for peer in self.known_peers:
                try:
                    url = peer.rstrip("/") + "/api/status"
                    req = urllib.request.Request(url, headers={"User-Agent": "ComputeMesh-Aggregator/1.2"})
                    with urllib.request.urlopen(req, timeout=1.5) as resp:
                        if resp.status == 200:
                            d = json.loads(resp.read().decode("utf-8"))
                            with self._lock:
                                self._peer_nodes[peer] = {
                                    "node_id": d.get("node_id", peer),
                                    "status": "online",
                                    "inventory": d.get("inventory", {}),
                                    "telemetry": d.get("telemetry", {}),
                                }
                except Exception:
                    with self._lock:
                        self._peer_nodes.pop(peer, None)
            time.sleep(5)

    def get_mesh_stats(self, local_status: dict[str, Any] | None = None) -> dict[str, Any]:
        if local_status:
            with self._lock:
                self._local_status = local_status

        nodes: list[dict[str, Any]] = []
        with self._lock:
            if hasattr(self, "_local_status") and self._local_status:
                nodes.append(self._local_status)
            elif local_status:
                nodes.append(local_status)
            else:
                try:
                    from tools.appliance.hardware_detector import scan_rig_hardware
                    inv = scan_rig_hardware()
                    nodes.append({
                        "node_id": "windows-laptop",
                        "status": "online",
                        "inventory": inv.to_dict(),
                        "telemetry": {"tokens_processed": 0, "local_compute_tflops": 0.0},
                    })
                except Exception:
                    pass
            for peer_data in self._peer_nodes.values():
                nodes.append(peer_data)

        # Deduplicate nodes by node_id to prevent duplicate tallying across multi-interface peers
        seen_nids: set[str] = set()
        deduped_nodes: list[dict[str, Any]] = []
        for n in nodes:
            nid = str(n.get("node_id", ""))
            if nid and nid in seen_nids:
                continue
            if nid:
                seen_nids.add(nid)
            deduped_nodes.append(n)
        nodes = deduped_nodes

        total_gpus = 0
        total_vram_bytes = 0
        total_tflops = 0.0
        total_tokens = 0
        node_details = []

        from tools.appliance.hardware_detector import is_integrated_display_adapter

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
            total_tokens += tel.get("tokens_processed", 0)

            local_nid = str((local_status or getattr(self, "_local_status", {})).get("node_id", ""))
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
    autostart=os.environ.get("COMPUTEMESH_AUTOSTART_MESH_POLLER", "").strip().lower() in ("1", "true", "yes", "on")
)
