"""P0 Comprehensive Regression Test Suite: Node Reboot Reconnect & Hardware Continuity.

Verifies that nodes (including volatile live-boot appliances like cm-inference-node-01)
automatically reconnect and rejoin the mesh after reboot without requiring manual re-enrollment,
token reconfiguration, or manual service restarts.
"""
from __future__ import annotations

from datetime import datetime, timezone, timedelta
import hashlib
from http import HTTPStatus
from http.server import ThreadingHTTPServer
import io
import json
from pathlib import Path
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

from services.billing.owner_accounts import OwnerAccountStore
from services.gateway.dashboard import NODE_TELEMETRY_REGISTRY
import services.gateway.server as gateway_server
from services.gateway.server import (
    GatewayHandler,
    _build_fleet_payload,
    owner_id_for_key,
)
from tools.appliance.appliance_config import (
    ApplianceConfig,
    load_appliance_config,
    save_system_config,
)
from services.appliance_dashboard.tunnel_relay import get_or_create_node_auth_token


class TestP0NodeRebootReconnect(unittest.TestCase):
    def setUp(self) -> None:
        NODE_TELEMETRY_REGISTRY.clear()
        self._temp_dir = tempfile.TemporaryDirectory()
        self.temp_path = Path(self._temp_dir.name)
        self.db_path = self.temp_path / "test_owner_accounts.db"
        self.original_store = gateway_server.OWNER_ACCOUNT_STORE
        gateway_server.OWNER_ACCOUNT_STORE = OwnerAccountStore(self.db_path)

        self.owner_key = "cm_owner_p0_reboot_key_123"
        self.owner_id = owner_id_for_key(self.owner_key)
        gateway_server.OWNER_ACCOUNT_STORE.ensure_owner(self.owner_id)

    def tearDown(self) -> None:
        gateway_server.OWNER_ACCOUNT_STORE = self.original_store
        NODE_TELEMETRY_REGISTRY.clear()
        self._temp_dir.cleanup()

    def test_save_and_load_system_config_persists_owner_key_and_auth_token(self) -> None:
        """Verify that save_system_config writes OWNER_KEY and AUTH_TOKEN to computemesh.env
        and that load_appliance_config reads them back reliably.
        """
        boot_env = self.temp_path / "computemesh.env"
        sys_json = self.temp_path / "config.json"

        cfg = ApplianceConfig(
            rig_name="cm-inference-node-01",
            owner_key="cm_owner_test_persist_999",
            payout_address="0x1234567890123456789012345678901234567890",
            coordinator_url="https://mesh.inetconnector.com",
            dashboard_port=8080,
        )

        with patch("tools.appliance.appliance_config.DEFAULT_BOOT_CONFIG", boot_env), \
             patch("tools.appliance.appliance_config.DEFAULT_LIVE_BOOT_CONFIG", self.temp_path / "nonexistent.env"):
            save_system_config(cfg, path=sys_json)

        self.assertTrue(boot_env.exists(), "computemesh.env must be written")
        env_content = boot_env.read_text(encoding="utf-8")
        self.assertIn("OWNER_KEY=cm_owner_test_persist_999", env_content)
        self.assertIn("AUTH_TOKEN=", env_content)

        # Now load it back
        loaded = load_appliance_config(boot_path=boot_env, system_path=sys_json)
        self.assertEqual(loaded.rig_name, "cm-inference-node-01")
        self.assertEqual(loaded.owner_key, "cm_owner_test_persist_999")

    def test_get_or_create_node_auth_token_hardware_continuity_across_reboots(self) -> None:
        """Verify that when local user directory is wiped (simulating live-boot RAM reboot),
        get_or_create_node_auth_token derives the exact same token via hardware identity.
        """
        isolated_home = self.temp_path / "isolated_home"
        isolated_home.mkdir(parents=True, exist_ok=True)

        with patch("pathlib.Path.home", return_value=isolated_home):
            # 1. First boot with no files: derives token from hardware identity
            token_1 = get_or_create_node_auth_token()
            self.assertTrue(token_1.startswith("cm_tunnel_"))
            self.assertEqual(len(token_1), 10 + 32)

            # 2. Simulate RAM wipe on reboot: delete any file in ~/.computemesh
            user_file = isolated_home / ".computemesh" / "node_auth_token.txt"
            if user_file.exists():
                user_file.unlink()

            # 3. Second boot on the same physical machine: token must be IDENTICAL
            token_2 = get_or_create_node_auth_token()
            self.assertEqual(token_1, token_2, "Hardware-derived token must remain identical across volatile reboots")

    def test_gateway_accepts_rebooted_node_via_hardware_continuity(self) -> None:
        """Verify that a node that reboots and presents a new token after being offline
        is accepted via hardware continuity proof (exact GPU signature and IP match),
        rather than being rejected with 401 Unauthorized.
        """
        now = datetime.now(timezone.utc)
        node_id = "cm-inference-node-01"
        client_ip = "192.168.1.27"
        old_token = "token_before_reboot_111"

        gpu_inventory = {
            "total_vram_bytes": 48 * 1024**3,
            "gpus": [
                {"vendor": "amd", "model_name": "AMD Radeon RX 580", "vram_bytes": 8 * 1024**3, "healthy": True}
                for _ in range(6)
            ],
        }

        # 1. Node was previously online and registered in NODE_TELEMETRY_REGISTRY
        NODE_TELEMETRY_REGISTRY[node_id] = {
            "node_id": node_id,
            "auth_token": old_token,
            "owner_id": self.owner_id,
            "client_ip": client_ip,
            "inventory": gpu_inventory,
            "machine_identity": {"machine_id": "hw1:abcdef1234567890abcdef1234567890abcdef1234567890abcdef1234567890"},
            "updated_at": (now - timedelta(seconds=400)).isoformat().replace("+00:00", "Z"), # 400s ago -> stale/offline
        }
        gateway_server.OWNER_ACCOUNT_STORE.bind_provider_node(self.owner_id, node_id)

        # Verify initial status in fleet is offline
        initial_fleet = _build_fleet_payload(self.owner_id)
        node_entry = next(n for n in initial_fleet["nodes"] if n["node_id"] == node_id)
        self.assertEqual(node_entry["status"], "offline")
        self.assertFalse(node_entry["is_online"])

        # 2. Node reboots: presents new token, same client IP and same hardware signature
        new_token = "token_after_reboot_222"
        heartbeat_body = {
            "node_id": node_id,
            "auth_token": new_token,
            "owner_key": "", # owner_key might be unconfigured on fresh ramdisk
            "inventory": gpu_inventory,
            "machine_identity": {"machine_id": "hw1:abcdef1234567890abcdef1234567890abcdef1234567890abcdef1234567890"},
            "telemetry": {"tokens_processed": 10},
        }

        server = ThreadingHTTPServer(("127.0.0.1", 0), GatewayHandler)
        server_port = server.server_address[1]
        server_thread = threading.Thread(target=server.serve_forever, daemon=True)
        server_thread.start()

        try:
            import urllib.request
            req = urllib.request.Request(
                f"http://127.0.0.1:{server_port}/api/v1/node/heartbeat",
                data=json.dumps(heartbeat_body).encode("utf-8"),
                headers={"Content-Type": "application/json", "X-Forwarded-For": client_ip},
            )
            with urllib.request.urlopen(req, timeout=5) as resp:
                resp_data = json.loads(resp.read().decode("utf-8"))
                self.assertEqual(resp.status, 200)
                self.assertEqual(resp_data.get("status"), "ok")

            # Verify registry has updated token and updated_at
            updated_node = NODE_TELEMETRY_REGISTRY[node_id]
            self.assertEqual(updated_node["auth_token"], new_token)
            self.assertEqual(updated_node["owner_id"], self.owner_id, "Owner binding must be preserved across reboot")

            # Verify fleet view immediately reports node as ONLINE
            fleet_after = _build_fleet_payload(self.owner_id)
            node_after = next(n for n in fleet_after["nodes"] if n["node_id"] == node_id)
            self.assertEqual(node_after["status"], "online")
            self.assertTrue(node_after["is_online"])

        finally:
            server.shutdown()
            server.server_close()

    def test_negative_security_attacker_rejected_with_401(self) -> None:
        """Verify fail-closed security: an attacker sending a mismatched token from a DIFFERENT
        IP or with DIFFERENT hardware is strictly rejected with 401 Unauthorized.
        """
        now = datetime.now(timezone.utc)
        node_id = "cm-inference-node-01"
        client_ip = "192.168.1.27"
        valid_token = "valid_token_xyz"

        NODE_TELEMETRY_REGISTRY[node_id] = {
            "node_id": node_id,
            "auth_token": valid_token,
            "owner_id": self.owner_id,
            "client_ip": client_ip,
            "inventory": {
                "gpus": [{"vendor": "amd", "model_name": "AMD Radeon RX 580", "vram_bytes": 8 * 1024**3, "healthy": True}]
            },
            "updated_at": (now - timedelta(seconds=400)).isoformat().replace("+00:00", "Z"),
        }

        # Attacker 1: Wrong IP, wrong token
        attacker_ip = "10.0.0.99"
        attacker_body = {
            "node_id": node_id,
            "auth_token": "spoofed_token_attacker",
            "inventory": {
                "gpus": [{"vendor": "amd", "model_name": "AMD Radeon RX 580", "vram_bytes": 8 * 1024**3, "healthy": True}]
            },
        }

        server = ThreadingHTTPServer(("127.0.0.1", 0), GatewayHandler)
        server_port = server.server_address[1]
        server_thread = threading.Thread(target=server.serve_forever, daemon=True)
        server_thread.start()

        try:
            import urllib.request
            req = urllib.request.Request(
                f"http://127.0.0.1:{server_port}/api/v1/node/heartbeat",
                data=json.dumps(attacker_body).encode("utf-8"),
                headers={"Content-Type": "application/json", "X-Forwarded-For": attacker_ip},
            )
            with self.assertRaises(urllib.error.HTTPError) as ctx:
                urllib.request.urlopen(req, timeout=5)
            self.assertEqual(ctx.exception.code, 401, "Attacker from different IP must be rejected with 401")

            # Attacker 2: Same IP, but DIFFERENT hardware signature (spoof attempt)
            attacker_hw_body = {
                "node_id": node_id,
                "auth_token": "spoofed_token_attacker",
                "inventory": {
                    "gpus": [{"vendor": "nvidia", "model_name": "NVIDIA GeForce RTX 4090", "vram_bytes": 24 * 1024**3, "healthy": True}]
                },
            }
            req2 = urllib.request.Request(
                f"http://127.0.0.1:{server_port}/api/v1/node/heartbeat",
                data=json.dumps(attacker_hw_body).encode("utf-8"),
                headers={"Content-Type": "application/json", "X-Forwarded-For": client_ip},
            )
            with self.assertRaises(urllib.error.HTTPError) as ctx2:
                urllib.request.urlopen(req2, timeout=5)
            self.assertEqual(ctx2.exception.code, 401, "Attacker with mismatched hardware must be rejected with 401")

        finally:
            server.shutdown()
            server.server_close()

    def test_ten_consecutive_reboots_simulation(self) -> None:
        """Test R2: 10 consecutive reboots.
        The node ID, hardware-derived token, and fleet ownership must never drift,
        and the node must successfully rejoin as ONLINE on every single reboot.
        """
        node_id = "cm-inference-node-01"
        client_ip = "192.168.1.27"
        gpu_inv = {
            "total_vram_bytes": 48 * 1024**3,
            "gpus": [{"vendor": "amd", "model_name": "AMD Radeon RX 580", "vram_bytes": 8 * 1024**3, "healthy": True} for _ in range(6)],
        }

        server = ThreadingHTTPServer(("127.0.0.1", 0), GatewayHandler)
        server_port = server.server_address[1]
        server_thread = threading.Thread(target=server.serve_forever, daemon=True)
        server_thread.start()

        try:
            import urllib.request
            # Initial enrollment
            token = get_or_create_node_auth_token()
            init_body = {
                "node_id": node_id,
                "auth_token": token,
                "owner_key": self.owner_key,
                "inventory": gpu_inv,
            }
            req = urllib.request.Request(
                f"http://127.0.0.1:{server_port}/api/v1/node/heartbeat",
                data=json.dumps(init_body).encode("utf-8"),
                headers={"Content-Type": "application/json", "X-Forwarded-For": client_ip},
            )
            with urllib.request.urlopen(req, timeout=5) as resp:
                self.assertEqual(resp.status, 200)

            # 10 Reboots
            for cycle in range(1, 11):
                # 1. Simulate node reboot: age expires past 300s
                NODE_TELEMETRY_REGISTRY[node_id]["updated_at"] = (
                    datetime.now(timezone.utc) - timedelta(seconds=350)
                ).isoformat().replace("+00:00", "Z")

                # Verify it went offline
                fleet_stale = _build_fleet_payload(self.owner_id)
                n_stale = next(n for n in fleet_stale["nodes"] if n["node_id"] == node_id)
                self.assertEqual(n_stale["status"], "offline")

                # 2. Node boots up, computes token from hardware identity
                boot_token = get_or_create_node_auth_token()
                self.assertEqual(boot_token, token, f"Token must be identical on reboot cycle {cycle}")

                # 3. Node sends heartbeat
                heartbeat = {
                    "node_id": node_id,
                    "auth_token": boot_token,
                    "owner_key": self.owner_key,
                    "inventory": gpu_inv,
                }
                hb_req = urllib.request.Request(
                    f"http://127.0.0.1:{server_port}/api/v1/node/heartbeat",
                    data=json.dumps(heartbeat).encode("utf-8"),
                    headers={"Content-Type": "application/json", "X-Forwarded-For": client_ip},
                )
                with urllib.request.urlopen(hb_req, timeout=5) as hb_resp:
                    self.assertEqual(hb_resp.status, 200)

                # 4. Fleet must report ONLINE
                fleet_live = _build_fleet_payload(self.owner_id)
                n_live = next(n for n in fleet_live["nodes"] if n["node_id"] == node_id)
                self.assertEqual(n_live["status"], "online", f"Node must be online on cycle {cycle}")
                self.assertTrue(n_live["is_online"])
                self.assertEqual(NODE_TELEMETRY_REGISTRY[node_id]["owner_id"], self.owner_id)

            # Verify no phantom duplicate nodes were created
            self.assertEqual(len(NODE_TELEMETRY_REGISTRY), 1)

        finally:
            server.shutdown()
            server.server_close()


if __name__ == "__main__":
    unittest.main()
