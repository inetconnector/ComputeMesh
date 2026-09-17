# SPDX-License-Identifier: Apache-2.0
"""Integration test ensuring Appliance Dashboard (port 8080) serves WebUI Chat Studio and AI routes."""
from __future__ import annotations

from http import HTTPStatus
import http.client
import json
from pathlib import Path
import sys
import threading
import time
import unittest

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from services.appliance_dashboard.server import create_dashboard_server
from tools.appliance.appliance_config import load_appliance_config
from tools.appliance.hardware_detector import scan_rig_hardware_stable


class TestApplianceWebUIIntegration(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cfg = load_appliance_config()
        inv = scan_rig_hardware_stable()
        cls.server, cls.port = create_dashboard_server(
            host="127.0.0.1",
            port=0,
            config=cfg,
            inventory=inv,
            node_id="test-webui-node",
        )
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        time.sleep(0.3)

    @classmethod
    def tearDownClass(cls) -> None:
        cls.server.shutdown()
        cls.server.server_close()

    def _get(self, path: str) -> tuple[int, bytes, dict[str, str]]:
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=5)
        conn.request("GET", path)
        resp = conn.getresponse()
        data = resp.read()
        headers = {k.lower(): v for k, v in resp.getheaders()}
        conn.close()
        return resp.status, data, headers

    def test_root_dashboard_has_chat_studio_links(self) -> None:
        status, data, _ = self._get("/")
        self.assertEqual(status, HTTPStatus.OK)
        html = data.decode("utf-8")
        self.assertIn("AI Chat Studio", html)
        self.assertIn("/webui/", html)

    def test_webui_static_index_served(self) -> None:
        for path in ("/webui", "/webui/", "/chat", "/chat/"):
            status, data, headers = self._get(path)
            self.assertEqual(status, HTTPStatus.OK, f"Failed for {path}")
            self.assertIn("text/html", headers.get("content-type", ""))
            html = data.decode("utf-8")
            self.assertIn("ComputeMesh AI Studio", html)

    def test_webui_props_endpoint(self) -> None:
        status, data, _ = self._get("/webui/props")
        self.assertEqual(status, HTTPStatus.OK)
        parsed = json.loads(data.decode("utf-8"))
        self.assertIn("webui_settings", parsed)
        self.assertIn("default_generation_settings", parsed)

    def test_webui_slots_endpoint(self) -> None:
        status, data, _ = self._get("/webui/slots")
        self.assertEqual(status, HTTPStatus.OK)
        parsed = json.loads(data.decode("utf-8"))
        self.assertIsInstance(parsed, list)
        self.assertEqual(len(parsed), 1)

    def test_webui_models_endpoint(self) -> None:
        status, data, _ = self._get("/webui/models")
        self.assertEqual(status, HTTPStatus.OK)
        parsed = json.loads(data.decode("utf-8"))
        self.assertIn("data", parsed)


if __name__ == "__main__":
    unittest.main()
