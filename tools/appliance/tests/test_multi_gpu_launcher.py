"""Unit tests for Multi-GPU inference allocation and command generation."""
import unittest

from tools.appliance.hardware_detector import GpuDevice, RigInventory
from tools.appliance.multi_gpu_launcher import (
    build_llama_server_command,
    compute_multi_gpu_allocation,
)


class TestMultiGpuLauncher(unittest.TestCase):
    def test_5x8gb_rig_proportional_split(self) -> None:
        """Simulate a classic 5x 8GB Ethereum mining rig (40GB VRAM total)."""
        gpus = [
            GpuDevice(
                index=i,
                pci_slot=f"0000:0{i+1}:00.0",
                vendor="nvidia",
                model_name="NVIDIA GeForce GTX 1070 8GB",
                vram_bytes=8 * 1024 * 1024 * 1024,
                pcie_gen=2,
                pcie_width=1,
                driver_backend="cuda",
                is_headless=False,
                healthy=True,
            )
            for i in range(5)
        ]
        inventory = RigInventory(
            schema_version=1,
            captured_at="2026-08-22T12:00:00Z",
            host_architecture="linux",
            total_gpus=5,
            total_vram_bytes=40 * 1024 * 1024 * 1024,
            gpus=gpus,
            pcie_riser_warning=True,
        )

        plan = compute_multi_gpu_allocation(inventory, total_model_layers=32)
        self.assertEqual(plan.total_gpus, 5)
        self.assertEqual(plan.total_vram_bytes, 40 * 1024 * 1024 * 1024)
        self.assertEqual(plan.total_model_layers, 32)
        
        # Verify layer allocation sums to 32
        assigned_sum = sum(a.allocated_layers for a in plan.allocations)
        self.assertEqual(assigned_sum, 32)
        
        # Verify tensor split argument
        self.assertEqual(plan.tensor_split_arg, "0.200,0.200,0.200,0.200,0.200")
        self.assertEqual(plan.devices_arg, "CUDA0,CUDA1,CUDA2,CUDA3,CUDA4")

        # Test commandline generation
        cmd = build_llama_server_command(
            executable="/opt/computemesh/llama-server",
            model_path="/var/lib/computemesh/models/qwen2.5-7b.gguf",
            plan=plan,
            host="0.0.0.0",
            port=8080,
        )
        self.assertIn("-ts", cmd)
        self.assertIn("0.200,0.200,0.200,0.200,0.200", cmd)
        self.assertIn("--devices", cmd)
        self.assertIn("CUDA0,CUDA1,CUDA2,CUDA3,CUDA4", cmd)


if __name__ == "__main__":
    unittest.main()
