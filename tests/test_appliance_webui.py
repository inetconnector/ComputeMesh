# SPDX-License-Identifier: Apache-2.0
"""Integration test ensuring Appliance Dashboard (port 8080) serves WebUI Chat Studio and AI routes."""
from __future__ import annotations

import hashlib
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


class TestWebUIStaticAssets(unittest.TestCase):
    def test_portal_and_android_model_selector_are_identical(self) -> None:
        portal_selector = REPO_ROOT / "portal" / "webui" / "model-selector.js"
        android_selector = REPO_ROOT / "apps" / "android" / "app" / "src" / "main" / "assets" / "webui" / "model-selector.js"
        self.assertTrue(portal_selector.is_file())
        self.assertTrue(android_selector.is_file())
        self.assertEqual(portal_selector.read_bytes(), android_selector.read_bytes())

    def test_agent_task_controls_use_durable_gateway_contract(self) -> None:
        selector = (REPO_ROOT / "portal" / "webui" / "model-selector.js").read_text(encoding="utf-8")
        self.assertIn("/v1/agents/sessions", selector)
        self.assertIn("/turns", selector)
        self.assertIn("environment_type: 'mesh'", selector)
        for locale in ("de", "en", "fr", "es", "it", "pt-BR", "nl", "pl", "tr"):
            self.assertTrue(
                locale + ": {" in selector or "'" + locale + "': {" in selector,
                f"missing localized agent task labels for {locale}",
            )
        self.assertIn("agentTaskCreateButton", selector)
        self.assertIn("agentTaskContinueButton", selector)
        self.assertIn("agentTaskPauseButton", selector)
        self.assertIn("agentTaskResumeButton", selector)
        self.assertIn("agentTaskCancelButton", selector)
        self.assertIn("/control", selector)
        self.assertIn("agentSessionActivityPanel", selector)
        self.assertIn("agentSessionActivity = agentSessionActivity.slice(-12)", selector)
        self.assertIn("agentSessionActivity.push({ label: describeAgentSessionEvent(event) })", selector)

    def test_android_lan_discovery_keeps_unknown_nodes_visible_without_trusting_them(self) -> None:
        discovery = (
            REPO_ROOT
            / "apps"
            / "android"
            / "app"
            / "src"
            / "main"
            / "java"
            / "com"
            / "inetconnector"
            / "compumesh"
            / "p2p"
            / "DirectLanDiscovery.kt"
        ).read_text(encoding="utf-8")
        server = (
            REPO_ROOT
            / "apps"
            / "android"
            / "app"
            / "src"
            / "main"
            / "java"
            / "com"
            / "inetconnector"
            / "compumesh"
            / "server"
            / "LocalChatServer.kt"
        ).read_text(encoding="utf-8")
        ui = (
            REPO_ROOT
            / "apps"
            / "android"
            / "app"
            / "src"
            / "main"
            / "java"
            / "com"
            / "inetconnector"
            / "compumesh"
            / "ui"
            / "tabs"
            / "LanMeshTab.kt"
        ).read_text(encoding="utf-8")
        self.assertIn('lifecycle: String = "discovered"', discovery)
        self.assertIn('requiresAuth: Boolean = false', discovery)
        self.assertIn('manual_pairing_required', discovery)
        self.assertIn('fetchModels(peer.targetUrl, "", allowCredentials = false)', server)
        self.assertIn('/v1/mesh/peers', server)
        self.assertIn('peer.isLocalLan && !peer.isAvailable', server)
        self.assertIn('peer.requiresAuth', ui)

    def test_pointer_event_rules_and_service_worker_revision_match(self) -> None:
        assets = (
            REPO_ROOT / "portal" / "webui",
            REPO_ROOT / "apps" / "android" / "app" / "src" / "main" / "assets" / "webui",
        )
        for webui_root in assets:
            index = webui_root / "index.html"
            service_worker = webui_root / "sw.js"
            html = index.read_text(encoding="utf-8")
            self.assertNotIn(
                '[class*="pointer-events-none"]',
                html,
                f"variant utility tokens must not disable controls in {index}",
            )
            self.assertIn(
                ".pointer-events-none:not(aside):not(aside *)",
                html,
                f"hidden trigger rule is missing from {index}",
            )
            revision = hashlib.md5(index.read_bytes()).hexdigest()
            self.assertIn(
                f'url:"./",revision:"{revision}"',
                service_worker.read_text(encoding="utf-8"),
                f"service-worker precache revision is stale for {index}",
            )


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
