# SPDX-License-Identifier: Apache-2.0
"""Integration test for Appliance WebUI Mesh Sharding, Distributed Cache & Stream Federation API endpoints."""
from __future__ import annotations

import http.client
import json
import sys
import threading
import time
import unittest
from http import HTTPStatus
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from services.appliance_dashboard.server import create_dashboard_server
from tools.appliance.appliance_config import load_appliance_config
from tools.appliance.hardware_detector import scan_rig_hardware_stable


class TestApplianceMeshShardingEndpoints(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cfg = load_appliance_config()
        inv = scan_rig_hardware_stable()
        cls.server, cls.port = create_dashboard_server(
            host="127.0.0.1",
            port=0,
            config=cfg,
            inventory=inv,
            node_id="test-sharding-node",
        )
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        time.sleep(0.3)

    @classmethod
    def tearDownClass(cls) -> None:
        cls.server.shutdown()
        cls.server.server_close()

    def _get(self, path: str) -> tuple[int, dict]:
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=5)
        conn.request("GET", path)
        resp = conn.getresponse()
        data = resp.read()
        conn.close()
        return resp.status, json.loads(data.decode("utf-8"))

    def _post(self, path: str, payload: dict) -> tuple[int, dict]:
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=5)
        body = json.dumps(payload).encode("utf-8")
        conn.request("POST", path, body=body, headers={"Content-Type": "application/json"})
        resp = conn.getresponse()
        data = resp.read()
        conn.close()
        return resp.status, json.loads(data.decode("utf-8"))

    def test_sharding_plan_endpoint(self) -> None:
        status, parsed = self._get("/api/v1/mesh/sharding/plan")
        self.assertEqual(status, HTTPStatus.OK)
        self.assertIn("sharding_plan", parsed)
        plan = parsed["sharding_plan"]
        self.assertIn("model_id", plan)
        self.assertIn("feasible", plan)

    def test_cache_status_endpoint(self) -> None:
        status, parsed = self._get("/api/v1/mesh/cache/status")
        self.assertEqual(status, HTTPStatus.OK)
        self.assertIn("distributed_model_cache", parsed)

    def test_stream_status_endpoint(self) -> None:
        status, parsed = self._get("/api/v1/mesh/stream/status")
        self.assertEqual(status, HTTPStatus.OK)
        self.assertIn("p2p_stream_federation", parsed)


if __name__ == "__main__":
    unittest.main()
