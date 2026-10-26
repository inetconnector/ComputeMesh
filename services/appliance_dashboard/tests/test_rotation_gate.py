"""Fail-closed contract for emergency-only local node token rotation."""
from __future__ import annotations

from http import HTTPStatus
import unittest
from unittest.mock import patch

from services.appliance_dashboard.system_actions import SystemActionsHandler


class _Recorder:
    def __init__(self):
        self.payload = None
        self.status = None

    def _send_json(self, payload, status=HTTPStatus.OK):
        self.payload = payload
        self.status = status


class TestNodeTokenRotationGate(unittest.TestCase):
    def test_local_rotation_disabled_by_default(self):
        handler = _Recorder()
        with patch.dict("os.environ", {"COMPUTEMESH_NODEOS": "1"}, clear=True):
            with patch(
                "services.appliance_dashboard.tunnel_relay.rotate_node_auth_token"
            ) as rotation:
                handled = SystemActionsHandler.handle_post(
                    handler, "/api/action/rotate_node_token", b"{}", "test"
                )
        self.assertTrue(handled)
        self.assertEqual(handler.status, HTTPStatus.CONFLICT)
        self.assertEqual(handler.payload["code"], "fleet_rotation_required")
        rotation.assert_not_called()

    def test_explicit_emergency_override_required(self):
        handler = _Recorder()
        with patch.dict(
            "os.environ",
            {"COMPUTEMESH_ENABLE_EMERGENCY_NODE_TOKEN_ROTATION": "1"},
            clear=True,
        ):
            with patch(
                "services.appliance_dashboard.tunnel_relay.rotate_node_auth_token",
                return_value="cm_tunnel_emergency_only",
            ) as rotation:
                handled = SystemActionsHandler.handle_post(
                    handler, "/api/action/rotate_node_token", b"{}", "test"
                )
        self.assertTrue(handled)
        self.assertEqual(handler.status, HTTPStatus.OK)
        self.assertEqual(handler.payload["node_token"], "cm_tunnel_emergency_only")
        rotation.assert_called_once_with()


if __name__ == "__main__":
    unittest.main()
