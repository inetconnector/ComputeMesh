# SPDX-License-Identifier: Apache-2.0
"""Comprehensive test suite for the ComputeMesh Kill Switch & Safety Subsystem."""
from __future__ import annotations

import datetime
from datetime import UTC, datetime, timedelta
import json
import os
from pathlib import Path
import sys
import tempfile
import time
import unittest

# Ensure project root is on sys.path
REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from runtime.safety.dead_mans_switch import (
    AuthorizationLeaseExpiredError,
    DeadMansLeaseGuard,
    EmergencyKillTrippedError,
    ExecutionLease,
    InvalidLeaseSignatureError,
    KillSwitchError,
    get_lease_guard,
    set_global_lease_guard,
    utc_now,
    utc_now_iso,
)
from runtime.safety.hardware_relay import (
    GPIOApplianceRelay,
    HardwareKillRelay,
    NullHardwareRelay,
    SmartPDUWebhookRelay,
)
from runtime.safety.supervisor import SafetySupervisor
from runtime.safety.tripline_monitor import TriplineMonitor
from tools.security.ed25519_verify import verify_ed25519_signature


class TestDeadMansSwitchAndLease(unittest.TestCase):
    """Test Positive Authorization Lease verification, expiration, and trip state."""

    def setUp(self) -> None:
        from cryptography.hazmat.primitives.asymmetric import ed25519
        self.priv = ed25519.Ed25519PrivateKey.generate()
        self.pub = self.priv.public_key()
        self.pub_hex = self.pub.public_bytes_raw().hex()

        self.guard = DeadMansLeaseGuard(
            node_id="test-node-01",
            supervisor_public_key_hex=self.pub_hex,
            default_ttl_seconds=15.0,
        )

    def sign_lease(self, lease: ExecutionLease) -> ExecutionLease:
        data = lease.canonical_bytes()
        sig = self.priv.sign(data)
        return ExecutionLease(
            lease_id=lease.lease_id,
            node_id=lease.node_id,
            issued_at_iso=lease.issued_at_iso,
            expires_at_iso=lease.expires_at_iso,
            ttl_seconds=lease.ttl_seconds,
            scope=lease.scope,
            tripline_status=lease.tripline_status,
            signature_hex=sig.hex(),
            metadata=lease.metadata,
        )

    def test_valid_signed_lease_authorizes(self) -> None:
        now = utc_now()
        exp = now + timedelta(seconds=10)
        raw_lease = ExecutionLease(
            lease_id="lease-001",
            node_id="test-node-01",
            issued_at_iso=now.isoformat().replace("+00:00", "Z"),
            expires_at_iso=exp.isoformat().replace("+00:00", "Z"),
            ttl_seconds=10.0,
        )
        signed = self.sign_lease(raw_lease)
        self.assertTrue(self.guard.update_lease(signed))
        self.assertTrue(self.guard.is_authorized())
        self.assertEqual(self.guard.assert_authorized().lease_id, "lease-001")
        self.assertGreater(self.guard.time_to_live_seconds(), 5.0)

    def test_invalid_signature_fails_verification(self) -> None:
        now = utc_now()
        exp = now + timedelta(seconds=10)
        invalid_lease = ExecutionLease(
            lease_id="lease-tampered",
            node_id="test-node-01",
            issued_at_iso=now.isoformat().replace("+00:00", "Z"),
            expires_at_iso=exp.isoformat().replace("+00:00", "Z"),
            ttl_seconds=10.0,
            signature_hex="deadbeef" * 8,  # invalid signature
        )
        with self.assertRaises(InvalidLeaseSignatureError):
            self.guard.update_lease(invalid_lease)
        self.assertFalse(self.guard.is_authorized())

    def test_expired_lease_rejected_immediately(self) -> None:
        now = utc_now()
        expired_time = now - timedelta(seconds=2)
        raw_lease = ExecutionLease(
            lease_id="lease-expired",
            node_id="test-node-01",
            issued_at_iso=(now - timedelta(seconds=20)).isoformat().replace("+00:00", "Z"),
            expires_at_iso=expired_time.isoformat().replace("+00:00", "Z"),
            ttl_seconds=15.0,
        )
        signed = self.sign_lease(raw_lease)
        with self.assertRaises(AuthorizationLeaseExpiredError):
            self.guard.update_lease(signed)

    def test_emergency_trip_state(self) -> None:
        now = utc_now()
        exp = now + timedelta(seconds=10)
        raw_lease = ExecutionLease(
            lease_id="lease-002",
            node_id="test-node-01",
            issued_at_iso=now.isoformat().replace("+00:00", "Z"),
            expires_at_iso=exp.isoformat().replace("+00:00", "Z"),
            ttl_seconds=10.0,
        )
        signed = self.sign_lease(raw_lease)
        self.guard.update_lease(signed)
        self.assertTrue(self.guard.is_authorized())

        # Trip the kill switch
        self.guard.trip("Operator Emergency Abort Test")
        self.assertTrue(self.guard.is_tripped)
        self.assertFalse(self.guard.is_authorized())
        with self.assertRaises(EmergencyKillTrippedError):
            self.guard.assert_authorized()

        # Attempt to ingest a lease while tripped must be rejected
        with self.assertRaises(EmergencyKillTrippedError):
            self.guard.update_lease(signed)


class TestHardwareRelays(unittest.TestCase):
    """Test Hardware Power / Network Relays."""

    def test_null_relay(self) -> None:
        relay = NullHardwareRelay()
        self.assertTrue(relay.trip_hardware("Simulated Trip"))
        st = relay.get_status()
        self.assertTrue(st["tripped"])
        self.assertEqual(st["last_reason"], "Simulated Trip")
        self.assertTrue(relay.restore_hardware())
        self.assertFalse(relay.get_status()["tripped"])

    def test_smart_pdu_relay_mock(self) -> None:
        pdu = SmartPDUWebhookRelay(cutoff_url="http://127.0.0.1:9999/pdu/off", auth_token="secret-pdu", timeout_seconds=0.01)
        self.assertFalse(pdu.tripped)
        from unittest.mock import patch, MagicMock
        with patch("urllib.request.urlopen") as mock_open:
            mock_resp = MagicMock()
            mock_resp.status = 200
            mock_resp.__enter__.return_value = mock_resp
            mock_open.return_value = mock_resp
            self.assertTrue(pdu.trip_hardware("PDU Test Abort"))
            self.assertTrue(pdu.tripped)
            st = pdu.get_status()
            self.assertEqual(st["relay_type"], "SmartPDUWebhookRelay")

    def test_gpio_relay_mock(self) -> None:
        gpio = GPIOApplianceRelay(pin=18)
        self.assertTrue(gpio.trip_hardware("GPIO Test Abort"))
        st = gpio.get_status()
        self.assertTrue(st["tripped"])
        self.assertEqual(st["pin"], 18)


class TestTriplineMonitor(unittest.TestCase):
    """Test FIM and anomaly tripline watcher."""

    def test_fim_detects_tampering(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            test_file = Path(tmp_dir) / "critical_binary.py"
            test_file.write_text("INITIAL_BINARY_BYTES = 1\n", encoding="utf-8")

            breached_events = []

            def on_breach(name: str, details: str) -> None:
                breached_events.append((name, details))

            monitor = TriplineMonitor(
                on_breach_callback=on_breach,
                monitored_paths=[test_file],
            )
            # Baseline is valid
            ok, err = monitor.verify_integrity_now()
            self.assertTrue(ok)
            self.assertIsNone(err)

            # Modify the monitored file
            test_file.write_text("TAMPERED_MALICIOUS_BYTES = 999\n", encoding="utf-8")

            # Verify integrity detects modification
            ok2, err2 = monitor.verify_integrity_now()
            self.assertFalse(ok2)
            self.assertIsNotNone(err2)
            self.assertEqual(len(breached_events), 1)
            self.assertEqual(breached_events[0][0], "FIM_MODIFICATION")


class TestSafetySupervisor(unittest.TestCase):
    """Test SafetySupervisor heartbeat issuing and positive authorization loop."""

    def setUp(self) -> None:
        from cryptography.hazmat.primitives.asymmetric import ed25519
        self.priv = ed25519.Ed25519PrivateKey.generate()
        self.priv_bytes = self.priv.private_bytes_raw()
        self.pub_hex = self.priv.public_key().public_bytes_raw().hex()

    def test_supervisor_lease_generation(self) -> None:
        guard = DeadMansLeaseGuard(
            node_id="supervisor-test-node",
            supervisor_public_key_hex=self.pub_hex,
            default_ttl_seconds=15.0,
        )
        supervisor = SafetySupervisor(
            node_id="supervisor-test-node",
            guard=guard,
            master_private_key_bytes=self.priv_bytes,
            lease_ttl_seconds=15.0,
            renewal_interval_seconds=5.0,
            monitored_paths=[],
        )

        lease = supervisor.generate_lease()
        self.assertIsNotNone(lease)
        self.assertTrue(supervisor.renew_positive_authorization())
        self.assertTrue(guard.is_authorized())
        self.assertGreater(guard.time_to_live_seconds(), 5.0)

    def test_supervisor_emergency_kill(self) -> None:
        guard = DeadMansLeaseGuard(
            node_id="supervisor-test-node",
            supervisor_public_key_hex=self.pub_hex,
        )
        supervisor = SafetySupervisor(
            node_id="supervisor-test-node",
            guard=guard,
            master_private_key_bytes=self.priv_bytes,
            monitored_paths=[],
        )
        supervisor.renew_positive_authorization()
        self.assertTrue(guard.is_authorized())

        # Trigger emergency kill
        supervisor.emergency_kill(reason="Test Emergency Shutdown")
        self.assertTrue(supervisor.get_status()["is_tripped"])
        self.assertTrue(guard.is_tripped)
        self.assertFalse(guard.is_authorized())


class TestIntegrationKillSwitchInferenceAndTools(unittest.TestCase):
    """Test that Inference Engine and Tool Registry strictly block actions when killswitch is tripped."""

    def setUp(self) -> None:
        self.guard = DeadMansLeaseGuard(node_id="integration-test-node")
        set_global_lease_guard(self.guard)

    def tearDown(self) -> None:
        self.guard.reset()

    def test_tool_registry_blocks_when_killswitch_tripped(self) -> None:
        from services.mcp.tool_registry import ToolRegistry
        registry = ToolRegistry()
        registry.register_tool(
            "custom_safety_test_tool",
            "A test tool",
            {"type": "object", "properties": {"val": {"type": "integer"}}},
            lambda val: {"computed": val * 2},
        )

        # Tool works normally when not tripped
        res = registry.execute_tool("custom_safety_test_tool", {"val": 21})
        self.assertEqual(res.get("computed"), 42)

        # Trip killswitch
        self.guard.trip("Operator Emergency Trigger")

        # Tool execution is blocked immediately
        res_blocked = registry.execute_tool("custom_safety_test_tool", {"val": 21})
        self.assertIn("error", res_blocked)
        self.assertIn("Emergency Kill Switch ist aktiv", res_blocked["error"])


class TestMultiTenantFleetIsolation(unittest.TestCase):
    """Test strict multi-tenant isolation so a fleet operator can NEVER disrupt other fleets or global platform."""

    def setUp(self) -> None:
        from cryptography.hazmat.primitives.asymmetric import ed25519
        self.priv = ed25519.Ed25519PrivateKey.generate()
        self.pub_hex = self.priv.public_key().public_bytes_raw().hex()
        self.guard = DeadMansLeaseGuard(
            node_id="node-tenant-01",
            supervisor_public_key_hex=self.pub_hex,
            default_ttl_seconds=30.0,
        )
        set_global_lease_guard(self.guard)

        # Issue active lease
        now = utc_now()
        raw_lease = ExecutionLease(
            lease_id="lease-mt-01",
            node_id="node-tenant-01",
            issued_at_iso=now.isoformat().replace("+00:00", "Z"),
            expires_at_iso=(now + timedelta(seconds=20)).isoformat().replace("+00:00", "Z"),
            ttl_seconds=20.0,
        )
        sig = self.priv.sign(raw_lease.canonical_bytes())
        signed_lease = ExecutionLease(
            lease_id=raw_lease.lease_id,
            node_id=raw_lease.node_id,
            issued_at_iso=raw_lease.issued_at_iso,
            expires_at_iso=raw_lease.expires_at_iso,
            ttl_seconds=raw_lease.ttl_seconds,
            signature_hex=sig.hex(),
        )
        self.guard.update_lease(signed_lease)

    def tearDown(self) -> None:
        self.guard.reset()

    def test_fleet_isolation_trip_does_not_affect_other_fleets(self) -> None:
        from services.mcp.tool_registry import ToolRegistry
        registry = ToolRegistry()
        registry.register_tool(
            "echo_val",
            "Echo tool",
            {"type": "object", "properties": {"msg": {"type": "string"}}},
            lambda msg: {"echo": msg},
        )

        owner_a = "acct_provider_alice_gpu"
        owner_b = "acct_provider_bob_cluster"

        # Initially both owners are authorized
        self.assertTrue(self.guard.is_authorized(owner_id=owner_a))
        self.assertTrue(self.guard.is_authorized(owner_id=owner_b))
        self.assertEqual(registry.execute_tool("echo_val", {"msg": "hello"}, owner_id=owner_a).get("echo"), "hello")
        self.assertEqual(registry.execute_tool("echo_val", {"msg": "world"}, owner_id=owner_b).get("echo"), "world")

        # Provider Alice trips her own fleet
        trip_info = self.guard.trip_fleet(owner_a, reason="Alice GPU thermal safety trip")
        self.assertTrue(trip_info["is_tripped"])
        self.assertEqual(trip_info["trip_reason"], "Alice GPU thermal safety trip")

        # Provider Alice is blocked
        self.assertTrue(self.guard.is_fleet_tripped(owner_a))
        self.assertFalse(self.guard.is_authorized(owner_id=owner_a))
        with self.assertRaises(EmergencyKillTrippedError):
            self.guard.assert_authorized(owner_id=owner_a)

        res_a = registry.execute_tool("echo_val", {"msg": "hello"}, owner_id=owner_a)
        self.assertIn("error", res_a)
        self.assertIn("ist gestoppt", res_a["error"])

        # ZERO GLOBAL IMPACT: Global platform and Provider Bob remain 100% operational
        self.assertFalse(self.guard.is_tripped)
        self.assertFalse(self.guard.is_fleet_tripped(owner_b))
        self.assertTrue(self.guard.is_authorized(owner_id=owner_b))
        self.assertEqual(self.guard.assert_authorized(owner_id=owner_b).lease_id, "lease-mt-01")

        res_b = registry.execute_tool("echo_val", {"msg": "world"}, owner_id=owner_b)
        self.assertEqual(res_b.get("echo"), "world")

        # Alice resets her fleet
        self.assertTrue(self.guard.reset_fleet(owner_a, reason="Alice cooled down"))
        self.assertFalse(self.guard.is_fleet_tripped(owner_a))
        self.assertTrue(self.guard.is_authorized(owner_id=owner_a))
        self.assertEqual(registry.execute_tool("echo_val", {"msg": "hello again"}, owner_id=owner_a).get("echo"), "hello again")

    def test_node_isolation_trip_does_not_affect_other_nodes(self) -> None:
        node_1 = "node-gpu-rig-01"
        node_2 = "node-gpu-rig-02"

        # Node 1 is tripped
        self.guard.trip_node(node_1, reason="Node 1 Power Surge")
        self.assertTrue(self.guard.is_node_tripped(node_1))
        self.assertFalse(self.guard.is_authorized(node_id=node_1))
        with self.assertRaises(EmergencyKillTrippedError):
            self.guard.assert_authorized(node_id=node_1)

        # Node 2 remains completely unblocked
        self.assertFalse(self.guard.is_node_tripped(node_2))
        self.assertTrue(self.guard.is_authorized(node_id=node_2))
        self.assertEqual(self.guard.assert_authorized(node_id=node_2).lease_id, "lease-mt-01")

        # Reset Node 1
        self.assertTrue(self.guard.reset_node(node_1))
        self.assertFalse(self.guard.is_node_tripped(node_1))
        self.assertTrue(self.guard.is_authorized(node_id=node_1))

    def test_global_platform_kill_blocks_all_tenants_and_resets(self) -> None:
        owner_a = "acct_provider_alice_gpu"
        owner_b = "acct_provider_bob_cluster"

        # Master trips global platform
        self.guard.trip("Master platform emergency shutdown", is_master=True)
        self.assertTrue(self.guard.is_tripped)
        self.assertTrue(self.guard.is_fleet_tripped(owner_a))
        self.assertTrue(self.guard.is_fleet_tripped(owner_b))
        self.assertFalse(self.guard.is_authorized(owner_id=owner_a))
        self.assertFalse(self.guard.is_authorized(owner_id=owner_b))

        # Master resets global platform
        self.guard.reset("Master platform restored")
        self.assertFalse(self.guard.is_tripped)
        self.assertFalse(self.guard.is_fleet_tripped(owner_a))
        self.assertFalse(self.guard.is_fleet_tripped(owner_b))
        # Re-verify authorization after reset
        now = utc_now()
        raw_lease2 = ExecutionLease(
            lease_id="lease-mt-02",
            node_id="node-tenant-01",
            issued_at_iso=now.isoformat().replace("+00:00", "Z"),
            expires_at_iso=(now + timedelta(seconds=20)).isoformat().replace("+00:00", "Z"),
            ttl_seconds=20.0,
        )
        sig = self.priv.sign(raw_lease2.canonical_bytes())
        signed_lease2 = ExecutionLease(
            lease_id=raw_lease2.lease_id,
            node_id=raw_lease2.node_id,
            issued_at_iso=raw_lease2.issued_at_iso,
            expires_at_iso=raw_lease2.expires_at_iso,
            ttl_seconds=raw_lease2.ttl_seconds,
            signature_hex=sig.hex(),
        )
        self.guard.update_lease(signed_lease2)
        self.assertTrue(self.guard.is_authorized(owner_id=owner_a))
        self.assertTrue(self.guard.is_authorized(owner_id=owner_b))


if __name__ == "__main__":
    unittest.main()


