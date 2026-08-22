"""Unit tests for Node Health Monitor & Dynamic Failover Engine."""
import unittest

from services.scheduler.health_monitor import (
    HealthMonitorError,
    NodeHealthMonitor,
)
from services.scheduler.multi_gpu_planner import GpuDeviceSpec


class TestHealthMonitor(unittest.TestCase):
    def setUp(self) -> None:
        self.monitor = NodeHealthMonitor(heartbeat_timeout_seconds=10.0, max_gpu_temperature_c=85)

    def test_heartbeat_tracking_healthy(self) -> None:
        rec = self.monitor.record_heartbeat("node_01", gpu_temperatures_c=[55, 60, 58], now_utc=1000.0)
        self.assertEqual(rec.status, "HEALTHY")
        self.assertTrue(self.monitor.is_node_eligible("node_01", now_utc=1002.0))

    def test_thermal_overheating_marks_degraded(self) -> None:
        # GPU 2 is at 89°C (> 85°C threshold)
        rec = self.monitor.record_heartbeat("node_hot", gpu_temperatures_c=[60, 89, 62], now_utc=1000.0)
        self.assertEqual(rec.status, "DEGRADED")
        self.assertFalse(self.monitor.is_node_eligible("node_hot", now_utc=1001.0))

    def test_heartbeat_timeout_marks_offline(self) -> None:
        self.monitor.record_heartbeat("node_silence", now_utc=1000.0)
        # Check after 15 seconds (timeout is 10s)
        self.assertFalse(self.monitor.is_node_eligible("node_silence", now_utc=1015.0))
        states = self.monitor.evaluate_cluster_health(now_utc=1015.0)
        self.assertEqual(states["node_silence"], "OFFLINE")

    def test_penalty_accumulation_and_decay(self) -> None:
        self.monitor.record_heartbeat("node_flapping", now_utc=1000.0)
        self.monitor.record_node_failure("node_flapping", severity=5.0)
        self.assertEqual(self.monitor._nodes["node_flapping"].status, "DEGRADED")
        self.assertEqual(self.monitor._nodes["node_flapping"].penalty_score, 5.0)

        # Heartbeats decay penalty
        self.monitor.record_heartbeat("node_flapping", now_utc=1005.0)
        self.assertEqual(self.monitor._nodes["node_flapping"].penalty_score, 4.5)

    def test_failover_rebalance_evacuates_failed_node(self) -> None:
        gb8 = 8 * 1024 * 1024 * 1024
        devices = [
            GpuDeviceSpec(0, "GPU_0_Healthy", "nvidia", gb8),
            GpuDeviceSpec(1, "GPU_1_Failed", "amd", gb8),
            GpuDeviceSpec(2, "GPU_2_Healthy", "nvidia", gb8),
            GpuDeviceSpec(3, "GPU_3_Healthy", "amd", gb8),
        ]

        new_plan = self.monitor.failover_rebalance(
            model_id="qwen/qwen2.5-7b-instruct",
            total_layers=32,
            model_weight_bytes=4_000_000_000,
            all_candidate_devices=devices,
            failed_node_ids={"GPU_1_Failed"},
        )
        self.assertTrue(new_plan.is_feasible)
        self.assertEqual(len(new_plan.allocations), 3)
        assigned_names = [a.name for a in new_plan.allocations]
        self.assertNotIn("GPU_1_Failed", assigned_names)
        self.assertIn("GPU_0_Healthy", assigned_names)
        self.assertIn("GPU_2_Healthy", assigned_names)
        self.assertIn("GPU_3_Healthy", assigned_names)

    def test_all_nodes_failed_raises(self) -> None:
        gb8 = 8 * 1024 * 1024 * 1024
        devices = [GpuDeviceSpec(0, "GPU_0", "nvidia", gb8)]
        with self.assertRaises(HealthMonitorError):
            self.monitor.failover_rebalance(
                model_id="qwen/qwen2.5-7b-instruct",
                total_layers=32,
                model_weight_bytes=4_000_000_000,
                all_candidate_devices=devices,
                failed_node_ids={"GPU_0"},
            )


if __name__ == "__main__":
    unittest.main()
