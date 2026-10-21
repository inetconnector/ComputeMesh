# SPDX-License-Identifier: Apache-2.0
"""Integration test for Appliance WebUI Mesh Sharding, Distributed Cache, Stream Federation, Multi-Cluster, Zero-Trust, and Video Compression API endpoints."""
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
from services.appliance_dashboard.tunnel_relay import NODE_AUTH_TOKEN
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
        headers = {
            "Content-Type": "application/json",
            "X-Node-Auth-Token": NODE_AUTH_TOKEN,
        }
        conn.request("POST", path, body=body, headers=headers)
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

    def test_sharding_calculate_endpoint(self) -> None:
        payload = {
            "model_id": "meta-llama/Llama-3.3-70B-Instruct-GGUF",
            "total_layers": 80,
            "model_vram_bytes": 40 * 1024 * 1024 * 1024,
            "enable_tensor_parallel": True,
        }
        status, parsed = self._post("/api/v1/mesh/sharding/calculate", payload)
        self.assertEqual(status, HTTPStatus.OK)
        self.assertIn("sharding_plan", parsed)
        plan = parsed["sharding_plan"]
        self.assertEqual(plan["model_id"], "meta-llama/Llama-3.3-70B-Instruct-GGUF")
        self.assertTrue(plan["tensor_parallel_enabled"])

    def test_cache_status_endpoint(self) -> None:
        status, parsed = self._get("/api/v1/mesh/cache/status")
        self.assertEqual(status, HTTPStatus.OK)
        self.assertIn("distributed_model_cache", parsed)

    def test_cache_verify_endpoint(self) -> None:
        status, parsed = self._post("/api/v1/mesh/cache/verify", {"model_id": "nonexistent-model"})
        self.assertEqual(status, HTTPStatus.OK)
        self.assertIn("integrity", parsed)
        self.assertFalse(parsed["integrity"]["valid"])

    def test_stream_status_endpoint(self) -> None:
        status, parsed = self._get("/api/v1/mesh/stream/status")
        self.assertEqual(status, HTTPStatus.OK)
        self.assertIn("p2p_stream_federation", parsed)

    def test_federation_clusters_endpoint(self) -> None:
        status, parsed = self._get("/api/v1/mesh/federation/clusters")
        self.assertEqual(status, HTTPStatus.OK)
        self.assertIn("multi_cluster_federation", parsed)

    def test_federation_sync_endpoint(self) -> None:
        payload = {
            "clusters": [
                {
                    "cluster_id": "cluster-test-1",
                    "name": "Test Cluster 1",
                    "region": "eu-central",
                    "nodes": [
                        {
                            "node_id": "test-node-1",
                            "vram_bytes": 16 * 1024 * 1024 * 1024,
                            "tflops": 30.0,
                            "ping_ms": 10.0,
                            "is_active": True,
                        }
                    ],
                }
            ]
        }
        status, parsed = self._post("/api/v1/mesh/federation/sync", payload)
        self.assertEqual(status, HTTPStatus.OK)
        self.assertEqual(parsed["status"], "success")
        self.assertGreaterEqual(parsed["synced_clusters_count"], 1)

    def test_zero_trust_status_endpoint(self) -> None:
        status, parsed = self._get("/api/v1/mesh/zero_trust/status")
        self.assertEqual(status, HTTPStatus.OK)
        self.assertIn("zero_trust_worker_communication", parsed)

    def test_video_compression_status_endpoint(self) -> None:
        status, parsed = self._get("/api/v1/mesh/video/compression/status")
        self.assertEqual(status, HTTPStatus.OK)
        self.assertIn("adaptive_video_stream_compression", parsed)

    def test_video_compression_tune_endpoint(self) -> None:
        payload = {
            "rtt_ms": 15.0,
            "packet_loss_pct": 0.2,
            "bandwidth_kbps": 9000.0,
        }
        status, parsed = self._post("/api/v1/mesh/video/compression/tune", payload)
        self.assertEqual(status, HTTPStatus.OK)
        self.assertEqual(parsed["status"], "success")
        metrics = parsed["adaptive_video_stream_compression"]
        self.assertEqual(metrics["current_tier"], "ultra_hd")


if __name__ == "__main__":
    unittest.main()
