"""Unit tests for ComputeMesh mining rig hardware detection."""
import json
from pathlib import Path
import unittest

from tools.appliance.hardware_detector import GpuDevice, RigInventory, scan_rig_hardware


class TestHardwareDetector(unittest.TestCase):
    def test_rig_inventory_structure(self) -> None:
        mock_gpus = [
            GpuDevice(
                index=0,
                pci_slot="0000:01:00.0",
                vendor="nvidia",
                model_name="NVIDIA GeForce GTX 1070",
                vram_bytes=8 * 1024 * 1024 * 1024,
                pcie_gen=2,
                pcie_width=1,
                driver_backend="cuda",
                is_headless=False,
                healthy=True,
            ),
            GpuDevice(
                index=1,
                pci_slot="0000:02:00.0",
                vendor="nvidia",
                model_name="NVIDIA P106-100",
                vram_bytes=6 * 1024 * 1024 * 1024,
                pcie_gen=2,
                pcie_width=1,
                driver_backend="cuda",
                is_headless=True,
                healthy=True,
            ),
        ]
        inventory = RigInventory(
            schema_version=1,
            captured_at="2026-08-22T12:00:00Z",
            host_architecture="linux",
            total_gpus=2,
            total_vram_bytes=14 * 1024 * 1024 * 1024,
            gpus=mock_gpus,
            pcie_riser_warning=True,
        )

        d = inventory.to_dict()
        self.assertEqual(d["total_gpus"], 2)
        self.assertEqual(d["total_vram_bytes"], 14 * 1024 * 1024 * 1024)
        self.assertTrue(d["pcie_riser_warning"])
        self.assertTrue(d["gpus"][1]["is_headless"])

    def test_scan_rig_hardware_smoke(self) -> None:
        inv = scan_rig_hardware()
        self.assertIsInstance(inv, RigInventory)
        self.assertGreaterEqual(inv.total_gpus, 0)
        self.assertIsInstance(inv.to_dict(), dict)


if __name__ == "__main__":
    unittest.main()
