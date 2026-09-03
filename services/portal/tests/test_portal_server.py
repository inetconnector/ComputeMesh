"""Unit tests for ComputeMesh Public Web Portal & Registration Server."""
from http.server import ThreadingHTTPServer
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import threading
import time
import unittest
import urllib.error
import urllib.request

from services.portal.server import PortalHandler
from services.gateway.dashboard import NODE_TELEMETRY_REGISTRY
from services.portal.routes_registration import CURRENT_TERMS_VERSION


PORTAL_DIR = Path(__file__).resolve().parents[3] / "portal"
FORBIDDEN_BROWSER_ORIGINS = (
    "fonts.googleapis.com",
    "fonts.gstatic.com",
    "cdn.jsdelivr.net",
    "googletagmanager.com",
    "google-analytics.com",
    "connect.facebook.net",
)


def accepted_registration_payload(**overrides):
    body = {
        "email": "developer@ai-corp.com",
        "role": "consumer",
        "accepted_terms": True,
        "privacy_acknowledged": True,
        "business_user": True,
        "terms_version": CURRENT_TERMS_VERSION,
    }
    body.update(overrides)
    return body


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
            self.assertIn("Nutzungsbedingungen v2.1", content)
            self.assertIn("business-user-confirm", content)

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

    def test_portal_html_has_no_forbidden_third_party_resources(self) -> None:
        violations: list[str] = []
        for path in sorted(PORTAL_DIR.glob("*.html")):
            text = path.read_text(encoding="utf-8")
            for origin in FORBIDDEN_BROWSER_ORIGINS:
                if origin in text:
                    violations.append(f"{path.name}: {origin}")
        self.assertEqual(violations, [], "Forbidden third-party browser resources: " + ", ".join(violations))

    def test_serve_google_crawl_entrypoints(self) -> None:
        with urllib.request.urlopen("http://127.0.0.1:13000/robots.txt") as resp:
            self.assertEqual(resp.status, 200)
            self.assertEqual(resp.headers.get_content_type(), "text/plain")
            robots = resp.read().decode("utf-8")
            self.assertIn("User-agent: *", robots)
            self.assertIn("Sitemap: https://mesh.inetconnector.com/sitemap.xml", robots)
        with urllib.request.urlopen("http://127.0.0.1:13000/sitemap.xml") as resp:
            self.assertEqual(resp.status, 200)
            self.assertEqual(resp.headers.get_content_type(), "application/xml")
            sitemap = resp.read().decode("utf-8")
            self.assertIn("<urlset", sitemap)
            self.assertIn("<loc>https://mesh.inetconnector.com/</loc>", sitemap)

    def test_serve_portal_css(self) -> None:
        with urllib.request.urlopen("http://127.0.0.1:13000/portal.css") as resp:
            self.assertEqual(resp.status, 200)
            self.assertIn("--accent-cyan", resp.read().decode("utf-8"))

    def test_serve_portal_js(self) -> None:
        with urllib.request.urlopen("http://127.0.0.1:13000/portal.js") as resp:
            self.assertEqual(resp.status, 200)
            wrapper = resp.read().decode("utf-8")
            self.assertIn("portal-core.js", wrapper)
            self.assertIn("compliantRegistration", wrapper)
        with urllib.request.urlopen("http://127.0.0.1:13000/portal-core.js") as resp:
            self.assertEqual(resp.status, 200)
            core = resp.read().decode("utf-8")
            self.assertIn("switchLanguage", core)
            self.assertIn("translations", core)

    def test_mesh_stats_api(self) -> None:
        NODE_TELEMETRY_REGISTRY.clear()
        with urllib.request.urlopen("http://127.0.0.1:13000/api/v1/mesh/stats") as resp:
            self.assertEqual(resp.status, 200)
            data = json.loads(resp.read().decode("utf-8"))
            self.assertEqual(data["source"], "not_configured")
            self.assertEqual(data["active_gpus"], 0)
            self.assertEqual(data["total_vram_gb"], 0)

    def test_mesh_stats_api_counts_only_fresh_heartbeats(self) -> None:
        NODE_TELEMETRY_REGISTRY.clear()
        now = datetime.now(timezone.utc)
        NODE_TELEMETRY_REGISTRY.update({
            "fresh-node": {
                "node_id": "fresh-node",
                "inventory": {
                    "gpus": [{"vram_bytes": 8 * 1024 * 1024 * 1024}],
                },
                "telemetry": {"local_compute_tflops": 24.0, "tokens_processed": 100},
                "updated_at": now.isoformat().replace("+00:00", "Z"),
            },
            "stale-node": {
                "node_id": "stale-node",
                "inventory": {
                    "gpus": [{"vram_bytes": 16 * 1024 * 1024 * 1024}],
                },
                "telemetry": {"local_compute_tflops": 48.0, "tokens_processed": 200},
                "updated_at": (now - timedelta(minutes=10)).isoformat().replace("+00:00", "Z"),
            },
        })
        try:
            with urllib.request.urlopen("http://127.0.0.1:13000/api/v1/mesh/stats") as resp:
                self.assertEqual(resp.status, 200)
                data = json.loads(resp.read().decode("utf-8"))
                self.assertEqual(data["source"], "authenticated_cluster")
                self.assertEqual(data["active_gpus"], 1)
                self.assertEqual(data["total_nodes"], 1)
                self.assertEqual(data["total_vram_gb"], 8.0)
        finally:
            NODE_TELEMETRY_REGISTRY.clear()

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

    def test_registration_fails_without_clickwrap(self) -> None:
        req = urllib.request.Request(
            "http://127.0.0.1:13000/api/v1/register",
            data=json.dumps({"email": "developer@ai-corp.com", "role": "consumer"}).encode("utf-8"),
            headers={"Content-Type": "application/json"},
        )
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            urllib.request.urlopen(req)
        self.assertEqual(ctx.exception.code, 400)

    def test_register_consumer_api(self) -> None:
        req = urllib.request.Request(
            "http://127.0.0.1:13000/api/v1/register",
            data=json.dumps(accepted_registration_payload()).encode("utf-8"),
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(req) as resp:
            self.assertEqual(resp.status, 201)
            data = json.loads(resp.read().decode("utf-8"))
            self.assertEqual(data["status"], "success")
            self.assertTrue(data["api_key"].startswith("cm_live_"))
            self.assertEqual(data["free_credit_granted_usd"], 10.0)
            self.assertEqual(data["terms_version"], CURRENT_TERMS_VERSION)

    def test_register_provider_api_encrypted_storage(self) -> None:
        wallet = "0x71a99C8D2F8b3A15b81a84511d7e26d0De42B12F"
        req = urllib.request.Request(
            "http://127.0.0.1:13000/api/v1/register",
            data=json.dumps(accepted_registration_payload(
                email="provider@mining-farm.io",
                role="provider",
                wallet=wallet,
                country_code="DE",
                provider_data_processing_terms_accepted=True,
                no_prompt_logging_attested=True,
            )).encode("utf-8"),
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(req) as resp:
            self.assertEqual(resp.status, 201)
            data = json.loads(resp.read().decode("utf-8"))
            self.assertEqual(data["status"], "success")
            self.assertTrue(data["api_key"].startswith("cm_provider_"))
            self.assertEqual(data["encryption"], "AES-256-GCM")
    def test_mesh_fleet_api(self) -> None:
        from services.gateway.server import OWNER_ACCOUNT_STORE, owner_id_for_key
        owner_key = "test_fleet_key_12345"
        owner_id = owner_id_for_key(owner_key)
        assert owner_id is not None
        OWNER_ACCOUNT_STORE.ensure_owner(owner_id)
        OWNER_ACCOUNT_STORE.bind_provider_node(owner_id, "fleet-node-01")

        now = datetime.now(timezone.utc)
        NODE_TELEMETRY_REGISTRY.clear()
        NODE_TELEMETRY_REGISTRY["fleet-node-01"] = {
            "node_id": "fleet-node-01",
            "inventory": {
                "gpus": [{"model_name": "NVIDIA RTX 4090", "vendor": "nvidia", "vram_bytes": 24 * 1024 * 1024 * 1024}],
            },
            "telemetry": {"local_compute_tflops": 82.5, "tokens_processed": 500},
            "updated_at": now.isoformat().replace("+00:00", "Z"),
        }
        NODE_TELEMETRY_REGISTRY["unrelated-node"] = {
            "node_id": "unrelated-node",
            "inventory": {
                "gpus": [{"model_name": "AMD MI25", "vendor": "amd", "vram_bytes": 16 * 1024 * 1024 * 1024}],
            },
            "telemetry": {"local_compute_tflops": 24.0, "tokens_processed": 100},
            "updated_at": now.isoformat().replace("+00:00", "Z"),
        }

        with urllib.request.urlopen(f"http://127.0.0.1:13000/api/v1/mesh/fleet?owner_key={owner_key}") as resp:
            self.assertEqual(resp.status, 200)
            data = json.loads(resp.read().decode("utf-8"))
            self.assertEqual(data["owner_id"], owner_id)
            self.assertEqual(data["total_nodes_bound"], 1)
            self.assertEqual(data["total_nodes_online"], 1)
            self.assertEqual(data["total_vram_gb"], 24.0)
            self.assertEqual(data["total_tflops"], 82.5)
            self.assertEqual(len(data["nodes"]), 1)
            self.assertEqual(data["nodes"][0]["node_id"], "fleet-node-01")


if __name__ == "__main__":
    unittest.main()

