"""Unit tests for ComputeMesh mining rig hardware detection."""
import json
from pathlib import Path
import unittest

from tools.appliance.hardware_detector import (
    GpuDevice,
    RigInventory,
    detect_vendor_backend,
    is_integrated_display_adapter,
    is_provider_compute_gpu,
    parse_size_to_bytes,
    scan_rig_hardware,
)


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

    def test_integrated_display_adapter_is_not_provider_compute(self) -> None:
        self.assertTrue(
            is_integrated_display_adapter(
                "intel",
                "Intel Corporation 2nd Generation Core Processor Family Integrated Graphics Controller",
            )
        )
        gpu = GpuDevice(
            index=0,
            pci_slot="0000:00:02.0",
            vendor="intel",
            model_name="Intel Corporation 2nd Generation Core Processor Family Integrated Graphics Controller",
            vram_bytes=8 * 1024 * 1024 * 1024,
            pcie_gen=None,
            pcie_width=1,
            driver_backend="sycl",
            is_headless=False,
            healthy=True,
        )
        self.assertFalse(is_provider_compute_gpu(gpu))

    def test_discrete_gpu_is_provider_compute(self) -> None:
        gpu = GpuDevice(
            index=0,
            pci_slot="0000:05:00.0",
            vendor="amd",
            model_name="AMD Instinct MI25",
            vram_bytes=8 * 1024 * 1024 * 1024,
            pcie_gen=3,
            pcie_width=16,
            driver_backend="vulkan",
            is_headless=False,
            healthy=True,
        )
        self.assertTrue(is_provider_compute_gpu(gpu))

    def test_vendor_detection_does_not_match_compatible_as_ati(self) -> None:
        vendor, backend = detect_vendor_backend(
            "0000:00:02.0 VGA compatible controller: Intel Corporation Integrated Graphics Controller [8086:0102]"
        )
        self.assertEqual(vendor, "intel")
        self.assertEqual(backend, "sycl")

    def test_parse_lspci_memory_size(self) -> None:
        self.assertEqual(parse_size_to_bytes("8G"), 8 * 1024 * 1024 * 1024)
        self.assertEqual(parse_size_to_bytes("256M"), 256 * 1024 * 1024)
        self.assertIsNone(parse_size_to_bytes("unknown"))


if __name__ == "__main__":
    unittest.main()
