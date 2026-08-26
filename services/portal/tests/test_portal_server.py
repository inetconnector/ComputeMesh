"""Unit tests for ComputeMesh Public Web Portal & Registration Server."""
from http.server import ThreadingHTTPServer
import json
from pathlib import Path
import threading
import time
import unittest
import urllib.error
import urllib.request

from services.portal.server import PortalHandler
from services.gateway.dashboard import NODE_TELEMETRY_REGISTRY


class TestPortalServer(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.server = ThreadingHTTPServer(("127.0.0.1", 13000), PortalHandler)
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        time.sleep(0.1)

    @classmethod
    def tearDownClass(cls) -> None:
        cls.server.shutdown()
        cls.server.server_close()

    def test_serve_index_html(self) -> None:
        with urllib.request.urlopen("http://127.0.0.1:13000/") as resp:
            self.assertEqual(resp.status, 200)
            content = resp.read().decode("utf-8")
            self.assertIn("ComputeMesh", content)
            self.assertIn("data-i18n", content)

    def test_serve_subpages(self) -> None:
        subpages = ["/docs", "/status", "/benchmarks", "/terms", "/privacy", "/impressum", "/contact"]
        for page in subpages:
            with self.subTest(page=page):
                with urllib.request.urlopen(f"http://127.0.0.1:13000{page}") as resp:
                    self.assertEqual(resp.status, 200)
                    content = resp.read().decode("utf-8")
                    self.assertIn("ComputeMesh", content)
                    self.assertIn("<!DOCTYPE html>", content)
                    self.assertIn('rel="canonical"', content)

    def test_serve_google_crawl_entrypoints(self) -> None:
        with urllib.request.urlopen("http://127.0.0.1:13000/robots.txt") as resp:
            self.assertEqual(resp.status, 200)
            self.assertEqual(resp.headers.get_content_type(), "text/plain")
            robots = resp.read().decode("utf-8")
            self.assertIn("User-agent: *", robots)
            self.assertIn("Sitemap: https://computemesh.inetconnector.com/sitemap.xml", robots)

        with urllib.request.urlopen("http://127.0.0.1:13000/sitemap.xml") as resp:
            self.assertEqual(resp.status, 200)
            self.assertEqual(resp.headers.get_content_type(), "application/xml")
            sitemap = resp.read().decode("utf-8")
            self.assertIn("<urlset", sitemap)
            self.assertIn("<loc>https://computemesh.inetconnector.com/</loc>", sitemap)

    def test_serve_portal_css(self) -> None:
        with urllib.request.urlopen("http://127.0.0.1:13000/portal.css") as resp:
            self.assertEqual(resp.status, 200)
            css = resp.read().decode("utf-8")
            self.assertIn("--accent-cyan", css)

    def test_serve_portal_js(self) -> None:
        with urllib.request.urlopen("http://127.0.0.1:13000/portal.js") as resp:
            self.assertEqual(resp.status, 200)
            js = resp.read().decode("utf-8")
            self.assertIn("switchLanguage", js)
            self.assertIn("translations", js)

    def test_mesh_stats_api(self) -> None:
        NODE_TELEMETRY_REGISTRY.clear()
        with urllib.request.urlopen("http://127.0.0.1:13000/api/v1/mesh/stats") as resp:
            self.assertEqual(resp.status, 200)
            data = json.loads(resp.read().decode("utf-8"))
            self.assertIn("active_gpus", data)
            self.assertIn("total_vram_gb", data)
            self.assertEqual(data["source"], "not_configured")
            self.assertEqual(data["active_gpus"], 0)
            self.assertEqual(data["total_vram_gb"], 0)

    def test_node_heartbeat_and_status_require_node_token(self) -> None:
        NODE_TELEMETRY_REGISTRY.clear()
        heartbeat = urllib.request.Request(
            "http://127.0.0.1:13000/api/v1/node/heartbeat",
            data=json.dumps({
                "node_id": "node-secure-01",
                "auth_token": "cm_tunnel_0123456789abcdef0123456789abcdef",
                "inventory": {},
                "telemetry": {},
            }).encode("utf-8"),
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(heartbeat) as resp:
            self.assertEqual(resp.status, 200)

        with self.assertRaises(urllib.error.HTTPError) as missing_ctx:
            urllib.request.urlopen("http://127.0.0.1:13000/api/v1/node/node-secure-01/status")
        self.assertEqual(missing_ctx.exception.code, 401)

        with urllib.request.urlopen(
            "http://127.0.0.1:13000/api/v1/node/node-secure-01/status?auth=cm_tunnel_0123456789abcdef0123456789abcdef"
        ) as resp:
            self.assertEqual(resp.status, 200)
            data = json.loads(resp.read().decode("utf-8"))
            self.assertEqual(data["node_id"], "node-secure-01")

    def test_register_consumer_api(self) -> None:
        req_data = json.dumps({"email": "developer@ai-corp.com", "role": "consumer"}).encode("utf-8")
        req = urllib.request.Request(
            "http://127.0.0.1:13000/api/v1/register",
            data=req_data,
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(req) as resp:
            self.assertEqual(resp.status, 201)
            data = json.loads(resp.read().decode("utf-8"))
            self.assertEqual(data["status"], "success")
            self.assertTrue(data["api_key"].startswith("cm_live_"))
            self.assertEqual(data["free_credit_granted_usd"], 10.0)

    def test_register_provider_api_encrypted_storage(self) -> None:
        wallet = "0x71a99C8D2F8b3A15b81a84511d7e26d0De42B12F"
        req_data = json.dumps({
            "email": "provider@mining-farm.io",
            "role": "provider",
            "wallet": wallet,
        }).encode("utf-8")
        req = urllib.request.Request(
            "http://127.0.0.1:13000/api/v1/register",
            data=req_data,
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(req) as resp:
            self.assertEqual(resp.status, 201)
            data = json.loads(resp.read().decode("utf-8"))
            self.assertEqual(data["status"], "success")
            self.assertTrue(data["api_key"].startswith("cm_provider_"))
            self.assertEqual(data["encryption"], "AES-256-GCM")
            self.assertEqual(data["payout_target_masked"], "0x71a9...B12F")


if __name__ == "__main__":
    unittest.main()
