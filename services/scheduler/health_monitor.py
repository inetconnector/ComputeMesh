#!/usr/bin/env python3
"""ComputeMesh Autonomous Node Health Monitor & Dynamic Failover Engine.

Continuously tracks node heartbeats, thermal states, and network fault metrics,
automatically triggering layer re-sharding and seamless failover when provider
mining rigs experience hardware degradation or unexpected disconnects.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
import math
from pathlib import Path
import sys
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from services.scheduler.multi_gpu_planner import (
    GpuDeviceSpec,
    MultiGpuPlan,
    plan_multi_gpu_rig,
)


class HealthMonitorError(RuntimeError):
    """Raised on unrecoverable cluster-wide health failures."""


@dataclass
class NodeHealthRecord:
    node_id: str
    last_heartbeat_utc: float
    status: str = "HEALTHY"  # 'HEALTHY', 'DEGRADED', 'OFFLINE'
    consecutive_failures: int = 0
    penalty_score: float = 0.0
    gpu_temperatures_c: list[int] = field(default_factory=list)
    memory_free_bytes: int = 0


class NodeHealthMonitor:
    def __init__(
        self,
        heartbeat_timeout_seconds: float = 15.0,
        max_gpu_temperature_c: int = 85,
        max_penalty_threshold: float = 10.0,
    ) -> None:
        self.heartbeat_timeout_seconds = heartbeat_timeout_seconds
        self.max_gpu_temperature_c = max_gpu_temperature_c
        self.max_penalty_threshold = max_penalty_threshold
        self._nodes: dict[str, NodeHealthRecord] = {}

    def record_heartbeat(
        self,
        node_id: str,
        *,
        gpu_temperatures_c: list[int] | None = None,
        memory_free_bytes: int = 0,
        now_utc: float | None = None,
    ) -> NodeHealthRecord:
        now = now_utc if now_utc is not None else datetime.now(timezone.utc).timestamp()
        temps = gpu_temperatures_c or []

        # Evaluate thermal status
        is_overheating = any(t > self.max_gpu_temperature_c for t in temps)
        status = "DEGRADED" if is_overheating else "HEALTHY"

        if node_id not in self._nodes:
            rec = NodeHealthRecord(
                node_id=node_id,
                last_heartbeat_utc=now,
                status=status,
                consecutive_failures=0,
                penalty_score=0.0,
                gpu_temperatures_c=temps,
                memory_free_bytes=memory_free_bytes,
            )
            self._nodes[node_id] = rec
        else:
            rec = self._nodes[node_id]
            rec.last_heartbeat_utc = now
            rec.gpu_temperatures_c = temps
            rec.memory_free_bytes = memory_free_bytes
            rec.consecutive_failures = 0
            rec.penalty_score = max(0.0, rec.penalty_score - 0.5)  # Decay penalty on good behavior
            rec.status = status

        return rec

    def record_node_failure(self, node_id: str, severity: float = 2.0) -> None:
        if node_id in self._nodes:
            rec = self._nodes[node_id]
            rec.consecutive_failures += 1
            rec.penalty_score += severity
            if rec.penalty_score >= self.max_penalty_threshold or rec.consecutive_failures >= 3:
                rec.status = "OFFLINE"
            else:
                rec.status = "DEGRADED"

    def evaluate_cluster_health(self, now_utc: float | None = None) -> dict[str, str]:
        """Evaluates and updates status for all registered nodes."""
        now = now_utc if now_utc is not None else datetime.now(timezone.utc).timestamp()
        states = {}
        for nid, rec in self._nodes.items():
            silence = now - rec.last_heartbeat_utc
            if silence > self.heartbeat_timeout_seconds:
                rec.status = "OFFLINE"
            states[nid] = rec.status
        return states

    def is_node_eligible(self, node_id: str, now_utc: float | None = None) -> bool:
        self.evaluate_cluster_health(now_utc)
        rec = self._nodes.get(node_id)
        if not rec:
            return False
        return rec.status == "HEALTHY"

    def failover_rebalance(
        self,
        *,
        model_id: str,
        total_layers: int,
        model_weight_bytes: int,
        all_candidate_devices: list[GpuDeviceSpec],
        failed_node_ids: set[str],
    ) -> MultiGpuPlan:
        """Excludes failed/degraded nodes and calculates an optimal failover re-sharding."""
        eligible_devices = [
            d for d in all_candidate_devices
            if f"node_{d.device_id}" not in failed_node_ids and d.name not in failed_node_ids
        ]

        if not eligible_devices:
            raise HealthMonitorError("No healthy GPU nodes available to satisfy failover rebalance.")

        return plan_multi_gpu_rig(
            model_id=model_id,
            total_layers=total_layers,
            model_weight_bytes=model_weight_bytes,
            devices=eligible_devices,
        )
