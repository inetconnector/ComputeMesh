import unittest
from types import SimpleNamespace

from services.appliance_dashboard.server import (
    DASHBOARD_SESSION_TOKEN,
    DashboardHandler,
)
from services.appliance_dashboard.tunnel_relay import NODE_AUTH_TOKEN


class TestDashboardAdminAuth(unittest.TestCase):
    @staticmethod
    def _request(ip: str, *, headers=None, path="/api/models/manage"):
        return SimpleNamespace(
            client_address=(ip, 12345),
            headers=headers or {},
            path=path,
        )

    def test_loopback_still_requires_explicit_token(self) -> None:
        self.assertFalse(DashboardHandler._verify_admin_auth(self._request("127.0.0.1")))

    def test_private_lan_client_is_not_implicitly_trusted(self) -> None:
        self.assertFalse(DashboardHandler._verify_admin_auth(self._request("192.168.1.44")))

    def test_remote_client_requires_exact_node_token(self) -> None:
        request = self._request("192.168.1.44", headers={"X-Node-Auth-Token": NODE_AUTH_TOKEN})
        self.assertTrue(DashboardHandler._verify_admin_auth(request))
        wrong = self._request("192.168.1.44", headers={"X-Node-Auth-Token": NODE_AUTH_TOKEN + "x"})
        self.assertFalse(DashboardHandler._verify_admin_auth(wrong))

    def test_remote_client_can_use_dashboard_session_cookie(self) -> None:
        request = self._request(
            "192.168.1.44",
            headers={"Cookie": f"cm_dashboard_session={DASHBOARD_SESSION_TOKEN}"},
        )
        self.assertTrue(DashboardHandler._verify_admin_auth(request))

    def test_query_token_is_not_accepted(self) -> None:
        request = self._request("192.168.1.44", path="/api/status?auth=" + NODE_AUTH_TOKEN)
        self.assertFalse(DashboardHandler._verify_admin_auth(request))

    def test_paired_owner_key_is_inference_only(self) -> None:
        DashboardHandler.config = SimpleNamespace(owner_key="inet-owner-test")
        inference = self._request(
            "192.168.1.44",
            headers={"Authorization": "Bearer inet-owner-test"},
            path="/v1/chat/completions",
        )
        self.assertTrue(DashboardHandler._verify_owner_inference_auth(inference))
        wrong = self._request(
            "192.168.1.44",
            headers={"X-Owner-Key": "inet-owner-wrong"},
            path="/v1/chat/completions",
        )
        self.assertFalse(DashboardHandler._verify_owner_inference_auth(wrong))
        public = self._request(
            "8.8.8.8",
            headers={"X-Owner-Key": "inet-owner-test"},
            path="/v1/chat/completions",
        )
        self.assertFalse(DashboardHandler._verify_owner_inference_auth(public))

    def test_get_dashboard_html_injects_token_when_provided(self) -> None:
        from services.appliance_dashboard.template_loader import get_dashboard_html
        anon_html = get_dashboard_html()
        self.assertNotIn('window.__CM_NODE_AUTH_TOKEN__ = "', anon_html)
        auth_html = get_dashboard_html(auth_token=NODE_AUTH_TOKEN)
        self.assertIn(f'window.__CM_NODE_AUTH_TOKEN__ = "{NODE_AUTH_TOKEN}";', auth_html)

    def test_loopback_token_endpoint_blocks_remote_and_cross_site(self) -> None:
        from http import HTTPStatus
        import json

        sent_json = []
        unauth_called = []

        class MockHandler:
            headers = {}
            client_address = ("192.168.1.50", 12345)
            path = "/api/appliance/loopback_token"

            def _send_unauthorized(self):
                unauth_called.append(True)

            def _send_json(self, payload, status=HTTPStatus.OK):
                sent_json.append((payload, status))

        # Remote IP -> unauthorized
        remote_h = MockHandler()
        DashboardHandler.do_GET(remote_h)
        self.assertTrue(unauth_called)
        self.assertEqual(len(sent_json), 0)

        # Cross-site from loopback -> unauthorized
        unauth_called.clear()
        cross_h = MockHandler()
        cross_h.client_address = ("127.0.0.1", 12345)
        cross_h.headers = {"Sec-Fetch-Site": "cross-site"}
        DashboardHandler.do_GET(cross_h)
        self.assertTrue(unauth_called)
        self.assertEqual(len(sent_json), 0)

        # Same-origin loopback -> succeeds with token
        unauth_called.clear()
        loop_h = MockHandler()
        loop_h.client_address = ("127.0.0.1", 12345)
        loop_h.headers = {"Sec-Fetch-Site": "same-origin"}
        DashboardHandler.do_GET(loop_h)
        self.assertFalse(unauth_called)
        self.assertEqual(len(sent_json), 1)
        payload, status = sent_json[0]
        self.assertEqual(status, HTTPStatus.OK)
        self.assertEqual(payload.get("token"), NODE_AUTH_TOKEN)
        self.assertEqual(payload.get("session"), DASHBOARD_SESSION_TOKEN)


if __name__ == "__main__":
    unittest.main()
