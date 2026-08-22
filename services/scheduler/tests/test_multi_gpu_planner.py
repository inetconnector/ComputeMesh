"""Unit tests for Multi-GPU Mining Rig & Heterogeneous Placement Engine."""
import unittest

from services.scheduler.multi_gpu_planner import (
    GpuDeviceSpec,
    MultiGpuPlanningError,
    plan_multi_gpu_rig,
)


class TestMultiGpuPlanner(unittest.TestCase):
    def test_5x8gb_homogeneous_mining_rig(self) -> None:
        # Classic 5x 8GB mining rig (40 GB aggregate VRAM)
        gb8 = 8 * 1024 * 1024 * 1024
        devices = [
            GpuDeviceSpec(device_id=i, name=f"AMD Radeon RX 580 (GPU {i})", vendor="amd", vram_bytes=gb8)
            for i in range(5)
        ]
        # Target: Qwen 2.5 32B (64 layers, ~18.5 GB weights)
        plan = plan_multi_gpu_rig(
            model_id="qwen/qwen2.5-32b-instruct",
            total_layers=64,
            model_weight_bytes=18_500_000_000,
            devices=devices,
        )
        self.assertTrue(plan.is_feasible)
        self.assertEqual(len(plan.allocations), 5)
        # Verify layer coverage
        total_assigned = sum(a.layers_assigned for a in plan.allocations)
        self.assertEqual(total_assigned, 64)
        self.assertEqual(plan.allocations[0].layer_start, 0)
        self.assertEqual(plan.allocations[-1].layer_end, 64)
        # Verify contiguous layer bounds
        for i in range(len(plan.allocations) - 1):
            self.assertEqual(plan.allocations[i].layer_end, plan.allocations[i + 1].layer_start)

    def test_heterogeneous_mixed_capacity_rig(self) -> None:
        # Mixed rig: 2x 8GB AMD + 2x 8GB NVIDIA + 1x 12GB NVIDIA = 44 GB VRAM
        gb8 = 8 * 1024 * 1024 * 1024
        gb12 = 12 * 1024 * 1024 * 1024
        devices = [
            GpuDeviceSpec(0, "AMD Radeon RX 590", "amd", gb8),
            GpuDeviceSpec(1, "AMD Radeon Vega 56", "amd", gb8),
            GpuDeviceSpec(2, "NVIDIA GeForce RTX 3070", "nvidia", gb8),
            GpuDeviceSpec(3, "NVIDIA GeForce RTX 3070", "nvidia", gb8),
            GpuDeviceSpec(4, "NVIDIA GeForce RTX 3060", "nvidia", gb12),
        ]
        plan = plan_multi_gpu_rig(
            model_id="qwen/qwen2.5-32b-instruct",
            total_layers=64,
            model_weight_bytes=18_500_000_000,
            devices=devices,
        )
        self.assertTrue(plan.is_feasible)
        # The 12GB GPU (GPU 4) must get more layers than the 8GB GPUs
        gpu12_layers = plan.allocations[4].layers_assigned
        gpu8_layers = plan.allocations[0].layers_assigned
        self.assertGreater(gpu12_layers, gpu8_layers)

    def test_insufficient_vram_fails_closed(self) -> None:
        # 2x 4GB GPUs = 8GB total vs 70B model (~40 GB weights)
        gb4 = 4 * 1024 * 1024 * 1024
        devices = [
            GpuDeviceSpec(0, "GPU 0", "amd", gb4),
            GpuDeviceSpec(1, "GPU 1", "nvidia", gb4),
        ]
        plan = plan_multi_gpu_rig(
            model_id="llama/llama-3.1-70b-instruct",
            total_layers=80,
            model_weight_bytes=40_000_000_000,
            devices=devices,
        )
        self.assertFalse(plan.is_feasible)
        self.assertIn("Insufficient total rig VRAM", plan.status_reason)

    def test_empty_devices_raises(self) -> None:
        with self.assertRaises(MultiGpuPlanningError):
            plan_multi_gpu_rig(
                model_id="qwen/qwen2.5-7b-instruct",
                total_layers=32,
                model_weight_bytes=4_000_000_000,
                devices=[],
            )


if __name__ == "__main__":
    unittest.main()
