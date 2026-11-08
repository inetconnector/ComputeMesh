"""Adversarial and penetration tests for ComputeMesh appliance security hardening.

Verifies:
1. Anti-DNS-Rebinding Host header whitelisting (RFC / OWASP guidelines).
2. Anti-CSRF and Private Network Access (PNA) boundary protections.
3. LAN information leak prevention (Owner key masking on LAN).
4. HttpOnly and SameSite=Strict cookie enforcement for token protection.
"""
from __future__ import annotations

import json
import threading
import time
import unittest
import urllib.error
import urllib.request
from http import HTTPStatus

from services.appliance_dashboard.server import (
    DASHBOARD_SESSION_TOKEN,
    DashboardHandler,
    create_dashboard_server,
)
from services.appliance_dashboard.tunnel_relay import NODE_AUTH_TOKEN
from tools.appliance.appliance_config import ApplianceConfig


class TestSecurityHardening(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # Configure a test config with a sensitive owner key
        cls.test_config = ApplianceConfig(
            rig_name="sec-hardened-node",
            provider_account_id="cm_0xsec123",
            owner_key="inet-a6d61474f6aa4280fbdf91d0e9b5fb5d5d137fc3",
            payout_address="0x1234567890abcdef1234567890abcdef12345678",
            ssh_authorized_keys=["ssh-rsa AAAAB3NzaC1yc2EAAAADAQABAAABAQ... test@key"],
        )
        DashboardHandler.config = cls.test_config

        cls.server, cls.port = create_dashboard_server(host="127.0.0.1", port=0)
        cls.server_thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.server_thread.start()
        time.sleep(0.1)

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()

    def test_dns_rebinding_attack_is_blocked_with_403(self) -> None:
        """Simulate DNS rebinding: attacker resolves evil.com to 127.0.0.1."""
        for evil_host in [
            "evil.com",
            "evil.com:8081",
            "attacker.net",
            "127.0.0.1.nip.io",
            "attacker.localhost",
            "bank.phishing.attacker.com",
        ]:
            req = urllib.request.Request(
                f"http://127.0.0.1:{self.port}/",
                headers={"Host": evil_host},
            )
            with self.assertRaises(urllib.error.HTTPError) as ctx:
                urllib.request.urlopen(req)
            self.assertEqual(ctx.exception.code, 403, f"Expected 403 for Host {evil_host}")

    def test_legitimate_host_headers_are_permitted(self) -> None:
        """Legitimate local and private network hosts must succeed."""
        for valid_host in [
            f"127.0.0.1:{self.port}",
            f"localhost:{self.port}",
            "127.0.0.1",
            "localhost",
            f"[::1]:{self.port}",
            f"192.168.1.50:{self.port}",
        ]:
            req = urllib.request.Request(
                f"http://127.0.0.1:{self.port}/",
                headers={"Host": valid_host},
            )
            with urllib.request.urlopen(req) as resp:
                self.assertEqual(resp.status, 200)

    def test_csrf_cross_site_request_to_loopback_token_is_rejected(self) -> None:
        """Browser making a cross-site request to loopback token must be rejected."""
        req = urllib.request.Request(
            f"http://127.0.0.1:{self.port}/api/appliance/loopback_token",
            headers={
                "Host": f"127.0.0.1:{self.port}",
                "Sec-Fetch-Site": "cross-site",
                "Origin": "https://evil.com",
            },
        )
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            urllib.request.urlopen(req)
        self.assertEqual(ctx.exception.code, 401)

    def test_loopback_token_endpoint_issues_httponly_samesite_cookie(self) -> None:
        """Acquiring a loopback token sets HttpOnly and SameSite=Strict cookie."""
        req = urllib.request.Request(
            f"http://127.0.0.1:{self.port}/api/appliance/loopback_token",
            headers={
                "Host": f"127.0.0.1:{self.port}",
                "Sec-Fetch-Site": "same-origin",
            },
        )
        with urllib.request.urlopen(req) as resp:
            self.assertEqual(resp.status, 200)
            cookie_hdr = resp.headers.get("Set-Cookie", "")
            self.assertIn("HttpOnly", cookie_hdr)
            self.assertIn("SameSite=Strict", cookie_hdr)
            self.assertIn("cm_dashboard_session=", cookie_hdr)

            data = json.loads(resp.read().decode("utf-8"))
            # Must return the safe ephemeral session token, NEVER the master node token from disk
            self.assertEqual(data.get("token"), DASHBOARD_SESSION_TOKEN)
            self.assertNotEqual(data.get("token"), NODE_AUTH_TOKEN)

    def test_lan_caller_receives_redacted_owner_key(self) -> None:
        """A caller from the LAN (not loopback) must receive masked secrets."""
        from services.appliance_dashboard.system_actions import SystemActionsHandler

        sent_json = []

        class MockLanHandler:
            client_address = ("192.168.1.105", 54321)
            headers = {"Host": "192.168.1.27:8081"}
            config = TestSecurityHardening.test_config

            def _verify_admin_auth(self):
                return False

            def _send_json(self, payload, status=HTTPStatus.OK):
                sent_json.append((payload, status))

        mock_h = MockLanHandler()
        ok = SystemActionsHandler.handle_get(mock_h, "/api/config", "1.2.0")
        self.assertTrue(ok)
        self.assertEqual(len(sent_json), 1)

        data, status = sent_json[0]
        self.assertEqual(status, HTTPStatus.OK)
        # Owner key must be masked
        self.assertNotEqual(data.get("owner_key"), "inet-a6d61474f6aa4280fbdf91d0e9b5fb5d5d137fc3")
        self.assertIn("...", data.get("owner_key", ""))
        self.assertTrue(data.get("owner_key", "").startswith("inet-a6d"))
        # SSH keys and payout address must be protected
        self.assertIsNone(data.get("ssh_authorized_keys"))
        self.assertIn("...", data.get("payout_address", ""))

    def test_loopback_caller_receives_full_owner_key(self) -> None:
        """Loopback caller (local dashboard / PNA fleet) receives the unmasked owner key."""
        from services.appliance_dashboard.system_actions import SystemActionsHandler

        sent_json = []

        class MockLoopbackHandler:
            client_address = ("127.0.0.1", 54321)
            headers = {"Host": "localhost:8081", "Sec-Fetch-Site": "same-origin"}
            config = TestSecurityHardening.test_config

            def _verify_admin_auth(self):
                return False

            def _send_json(self, payload, status=HTTPStatus.OK):
                sent_json.append((payload, status))

        mock_h = MockLoopbackHandler()
        ok = SystemActionsHandler.handle_get(mock_h, "/api/config", "1.2.0")
        self.assertTrue(ok)
        data, status = sent_json[0]
        self.assertEqual(data.get("owner_key"), "inet-a6d61474f6aa4280fbdf91d0e9b5fb5d5d137fc3")


if __name__ == "__main__":
    unittest.main()
