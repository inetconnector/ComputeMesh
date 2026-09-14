"""Unit tests for Appliance Dashboard /v1/images/generations Route."""
import json
import unittest
import urllib.request
import urllib.error
from http import HTTPStatus

from services.appliance_dashboard.server import create_dashboard_server
from tools.appliance.appliance_config import ApplianceConfig
from tools.appliance.hardware_detector import RigInventory

class TestDashboardImageRoute(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cfg = ApplianceConfig(rig_name="test-miner-node")
        inv = RigInventory(
            schema_version=1,
            captured_at="2026-09-13T22:00:00Z",
            host_architecture="x86_64",
            total_gpus=1,
            total_vram_bytes=16 * 1024 * 1024 * 1024,
            gpus=[],
            pcie_riser_warning=False,
        )
        cls.server, cls.port = create_dashboard_server(
            host="127.0.0.1",
            port=0,
            config=cfg,
            inventory=inv,
            node_id="test-miner-node"
        )
        import threading
        cls.th = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.th.start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()

    def test_image_generation_endpoint(self):
        url = f"http://127.0.0.1:{self.port}/v1/images/generations"
        payload = {
            "prompt": "Ein kleiner roter Roboter in einer Wiese",
            "size": "512x512",
        }
        data = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(
            url,
            data=data,
            headers={"Content-Type": "application/json", "Accept": "application/json"},
            method="POST"
        )
        with urllib.request.urlopen(req, timeout=30) as resp:
            self.assertEqual(resp.status, 200)
            res = json.loads(resp.read().decode("utf-8"))
            self.assertIn("data", res)
            self.assertTrue(len(res["data"]) > 0)
            self.assertIn("url", res["data"][0])
            self.assertTrue(res["data"][0]["url"].startswith("http") or res["data"][0]["url"].startswith("data:"))

if __name__ == "__main__":
    unittest.main()
