"""Unit tests for Embedded Appliance Web Dashboard."""
import json
import threading
import time
import unittest
import urllib.request

from services.appliance_dashboard.server import DashboardHandler, run_dashboard_server
from tools.appliance.appliance_config import ApplianceConfig
from tools.appliance.hardware_detector import GpuDevice, RigInventory


class TestDashboardServer(unittest.TestCase):
    def test_dashboard_endpoints(self) -> None:
        mock_config = ApplianceConfig(
            rig_name="test-rig",
            provider_account_id="cm_0xabc",
            payout_address="0x1234567890123456789012345678901234567890",
            coordinator_url="https://coord.test",
            network_mode="dhcp",
            static_ip=None,
            gateway=None,
            dns=None,
            enable_web_dashboard=True,
            dashboard_port=8999,
            allow_ssh=True,
            ssh_authorized_keys=None,
        )
        mock_inventory = RigInventory(
            schema_version=1,
            captured_at="2026-08-22T12:00:00Z",
            host_architecture="linux",
            total_gpus=1,
            total_vram_bytes=8 * 1024 * 1024 * 1024,
            gpus=[
                GpuDevice(
                    index=0,
                    pci_slot="0000:01:00.0",
                    vendor="nvidia",
                    model_name="NVIDIA GTX 1070",
                    vram_bytes=8 * 1024 * 1024 * 1024,
                    pcie_gen=2,
                    pcie_width=1,
                    driver_backend="cuda",
                    is_headless=False,
                    healthy=True,
                )
            ],
            pcie_riser_warning=True,
        )

        from http.server import ThreadingHTTPServer
        DashboardHandler.config = mock_config
        DashboardHandler.inventory = mock_inventory
        DashboardHandler.node_id = "cm-test-node"

        server = ThreadingHTTPServer(("127.0.0.1", 18999), DashboardHandler)
        th = threading.Thread(target=server.serve_forever, daemon=True)
        th.start()
        time.sleep(0.1)

        try:
            # Test HTML endpoint
            with urllib.request.urlopen("http://127.0.0.1:18999/") as resp:
                self.assertEqual(resp.status, 200)
                html = resp.read().decode("utf-8")
                self.assertIn("ComputeMesh NodeOS", html)

            # Test JSON Status endpoint
            with urllib.request.urlopen("http://127.0.0.1:18999/api/status") as resp:
                self.assertEqual(resp.status, 200)
                data = json.loads(resp.read().decode("utf-8"))
                self.assertEqual(data["node_id"], "test-rig")
                self.assertEqual(data["config"]["rig_name"], "test-rig")
                self.assertEqual(data["config"]["payout_address"], "0x1234567890123456789012345678901234567890")
                self.assertEqual(data["inventory"]["total_gpus"], 1)
                self.assertIsNotNone(data["global_mesh"])
                self.assertIn("total_nodes_online", data["global_mesh"])
        finally:
            server.shutdown()
            server.server_close()

    def test_placeholder_test_node_name_does_not_override_runtime_node_id(self) -> None:
        mock_config = ApplianceConfig(
            rig_name="test-node-custom",
            provider_account_id="cm_0xabc",
            payout_address="",
            coordinator_url="https://coord.test",
            network_mode="dhcp",
            static_ip=None,
            gateway=None,
            dns=None,
            enable_web_dashboard=True,
            dashboard_port=8998,
            allow_ssh=True,
            ssh_authorized_keys=None,
        )
        mock_inventory = RigInventory(
            schema_version=1,
            captured_at="2026-08-22T12:00:00Z",
            host_architecture="linux",
            total_gpus=0,
            total_vram_bytes=0,
            gpus=[],
            pcie_riser_warning=False,
        )

        from http.server import ThreadingHTTPServer
        DashboardHandler.config = mock_config
        DashboardHandler.inventory = mock_inventory
        DashboardHandler.node_id = "supersrv-trixie"

        server = ThreadingHTTPServer(("127.0.0.1", 18998), DashboardHandler)
        th = threading.Thread(target=server.serve_forever, daemon=True)
        th.start()
        time.sleep(0.1)

        try:
            with urllib.request.urlopen("http://127.0.0.1:18998/api/status") as resp:
                self.assertEqual(resp.status, 200)
                data = json.loads(resp.read().decode("utf-8"))
                self.assertEqual(data["node_id"], "supersrv-trixie")
                self.assertEqual(data["network"]["interfaces"][0]["url"], "https://mesh.inetconnector.com/node/supersrv-trixie?auth=[REDACTED]")
        finally:
            server.shutdown()
            server.server_close()

    def test_windows_platform_safety_and_status(self) -> None:
        mock_config = ApplianceConfig(
            rig_name="win-test-node",
            provider_account_id="cm_0xabc",
            payout_address="0x1111111111111111111111111111111111111111",
            coordinator_url="https://coord.test",
            network_mode="dhcp",
            static_ip=None,
            gateway=None,
            dns=None,
            enable_web_dashboard=True,
            dashboard_port=8997,
            allow_ssh=True,
            ssh_authorized_keys=None,
        )
        mock_inventory = RigInventory(
            schema_version=1,
            captured_at="2026-08-22T12:00:00Z",
            host_architecture="win32",
            total_gpus=1,
            total_vram_bytes=16 * 1024 * 1024 * 1024,
            gpus=[],
            pcie_riser_warning=False,
        )

        from http.server import ThreadingHTTPServer
        import urllib.error
        DashboardHandler.config = mock_config
        DashboardHandler.inventory = mock_inventory
        DashboardHandler.node_id = "win-test-node"

        server = ThreadingHTTPServer(("127.0.0.1", 18997), DashboardHandler)
        th = threading.Thread(target=server.serve_forever, daemon=True)
        th.start()
        time.sleep(0.1)

        try:
            # 1. Verify status has OS fields
            with urllib.request.urlopen("http://127.0.0.1:18997/api/status") as resp:
                self.assertEqual(resp.status, 200)
                data = json.loads(resp.read().decode("utf-8"))
                self.assertIn("os", data)
                self.assertIn("is_windows", data)
                self.assertIn("platform_name", data)

            # 2. Verify reboot is rejected on Windows
            import sys
            if sys.platform == "win32":
                req = urllib.request.Request("http://127.0.0.1:18997/api/action/reboot", data=b"{}", method="POST")
                with self.assertRaises(urllib.error.HTTPError) as ctx:
                    urllib.request.urlopen(req)
                self.assertEqual(ctx.exception.code, 400)

                # 3. Verify OS upgrade is rejected on Windows
                req_up = urllib.request.Request("http://127.0.0.1:18997/api/action/os_upgrade", data=b"{}", method="POST")
                with self.assertRaises(urllib.error.HTTPError) as ctx:
                    urllib.request.urlopen(req_up)
                self.assertEqual(ctx.exception.code, 400)
        finally:
            server.shutdown()
            server.server_close()


if __name__ == "__main__":
    unittest.main()
