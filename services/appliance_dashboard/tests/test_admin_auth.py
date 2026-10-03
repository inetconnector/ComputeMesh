from types import SimpleNamespace
import unittest

from services.appliance_dashboard.server import DASHBOARD_SESSION_TOKEN, DashboardHandler
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


if __name__ == "__main__":
    unittest.main()
