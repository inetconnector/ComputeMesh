"""Unit tests for ComputeMesh Android Node Protocol & Battery Guard."""
import json
from pathlib import Path
import sys
import unittest

REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from apps.android.android_node_relay import AndroidBatteryPolicy, AndroidNodeRelay


class TestAndroidNodeProtocol(unittest.TestCase):
    def test_battery_policy_charging_and_cool(self) -> None:
        policy = AndroidBatteryPolicy(
            is_charging=True,
            battery_pct=90,
            temperature_celsius=32.0,
            is_wifi_connected=True,
        )
        permitted, reason = policy.evaluate()
        self.assertTrue(permitted)
        self.assertIsNone(reason)

    def test_battery_policy_overheating_protection(self) -> None:
        policy = AndroidBatteryPolicy(
            is_charging=True,
            battery_pct=95,
            temperature_celsius=43.5,  # > 42.0°C limit
            is_wifi_connected=True,
        )
        permitted, reason = policy.evaluate()
        self.assertFalse(permitted)
        self.assertIn("Temperature too high", str(reason))

    def test_battery_policy_unplugged_restriction(self) -> None:
        policy = AndroidBatteryPolicy(
            is_charging=False,
            battery_pct=50,
            temperature_celsius=25.0,
            is_wifi_connected=True,
        )
        permitted, reason = policy.evaluate(allow_unplugged=False)
        self.assertFalse(permitted)
        self.assertIn("Device not connected to AC charger", str(reason))

    def test_battery_policy_cellular_data_protection(self) -> None:
        policy = AndroidBatteryPolicy(
            is_charging=True,
            battery_pct=100,
            temperature_celsius=26.0,
            is_wifi_connected=False,  # On cellular
        )
        permitted, reason = policy.evaluate()
        self.assertFalse(permitted)
        self.assertIn("Not connected to unmetered Wi-Fi", str(reason))

    def test_heartbeat_payload_structure(self) -> None:
        relay = AndroidNodeRelay(node_id="android-test-device", owner_key="test-owner-key")
        payload = relay.build_heartbeat_payload()

        self.assertEqual(payload["node_id"], "android-test-device")
        self.assertEqual(payload["owner_key"], "test-owner-key")
        self.assertEqual(payload["inventory"]["host_architecture"], "android_arm64")
        self.assertEqual(payload["software"]["model"], "openbmb/minicpm5-2b")
        self.assertTrue(payload["telemetry"]["is_compute_permitted"])


if __name__ == "__main__":
    unittest.main()
