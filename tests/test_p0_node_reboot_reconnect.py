"""P0 Comprehensive Regression & Cryptographic Node Security Test Suite.

Verifies:
1. Rejection of unauthenticated hardware-spoofing reconnect attempts (fail-closed 401).
2. Rejection of mismatched public keys and replayed expired timestamps.
3. Successful automatic reboot reconnect via Ed25519 cryptographic proof of possession.
4. Cryptographic random token generation (high entropy) without predictable machine_id hashing.
5. Strict exclusion and scrubbing of OWNER_KEY and AUTH_TOKEN from FAT32 boot media.
6. 10 consecutive reboot cycles with zero phantom node duplication and durable fleet ownership.
"""
from __future__ import annotations

from datetime import datetime, timezone, timedelta
import concurrent.futures
from http import HTTPStatus
from http.server import ThreadingHTTPServer
import json
import os
from pathlib import Path
import tempfile
import threading
import time
import unittest
from unittest.mock import patch
import urllib.error
import urllib.request

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

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
from tools.security.node_key_storage import (
    get_or_create_node_private_key,
    sign_node_heartbeat,
    verify_node_heartbeat,
)


class TestP0CryptographicNodeRebootSecurity(unittest.TestCase):
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

        # Generate test node Ed25519 identity
        self.node_private_key = Ed25519PrivateKey.generate()
        self.node_public_key_bytes = self.node_private_key.public_key().public_bytes(
            serialization.Encoding.Raw,
            serialization.PublicFormat.Raw,
        )
        self.node_public_key_hex = self.node_public_key_bytes.hex()
        self.node_id = "cm-inference-node-01"

    def tearDown(self) -> None:
        gateway_server.OWNER_ACCOUNT_STORE = self.original_store
        NODE_TELEMETRY_REGISTRY.clear()
        self._temp_dir.cleanup()

    def test_boot_partition_never_contains_owner_key_or_auth_token(self) -> None:
        """S3 Gate: Verify that save_system_config never writes secrets to FAT32 boot partition
        and actively scrubs any existing legacy secret lines.
        """
        boot_env = self.temp_path / "computemesh.env"
        # Seed with legacy vulnerable content
        boot_env.write_text(
            "NODE_NAME=cm-node\nOWNER_KEY=legacy_secret_key\nAUTH_TOKEN=legacy_token\nCOORDINATOR_URL=https://mesh.inetconnector.com\n",
            encoding="utf-8",
        )
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

        self.assertTrue(boot_env.exists(), "computemesh.env must exist")
        env_content = boot_env.read_text(encoding="utf-8")
        self.assertNotIn("OWNER_KEY", env_content, "OWNER_KEY must NEVER be written to boot media")
        self.assertNotIn("AUTH_TOKEN", env_content, "AUTH_TOKEN must NEVER be written to boot media")
        self.assertIn("NODE_NAME=cm-inference-node-01", env_content)
        self.assertIn("COORDINATOR_URL=https://mesh.inetconnector.com", env_content)

        # Verify secrets are safely persisted in protected system config
        self.assertTrue(sys_json.exists())
        sys_data = json.loads(sys_json.read_text(encoding="utf-8"))
        self.assertEqual(sys_data.get("owner_key"), "cm_owner_test_persist_999")

    def test_token_generation_uses_secure_entropy_not_machine_id(self) -> None:
        """S2 Gate: Verify that tokens are generated using high-entropy random secrets,
        NOT deterministically hashed from predictable machine_identity fields.
        """
        isolated_home = self.temp_path / "isolated_home"
        isolated_home.mkdir(parents=True, exist_ok=True)
        token_file = isolated_home / "node_auth_token.txt"

        token_1 = get_or_create_node_auth_token(search_paths=[token_file])
        self.assertTrue(token_1.startswith("cm_tunnel_"))
        self.assertGreaterEqual(len(token_1), 10 + 48)  # 24 bytes hex = 48 chars

        # Verify token was persisted to the isolated location
        self.assertTrue(token_file.exists())
        self.assertEqual(token_file.read_text(encoding="utf-8").strip(), token_1)

        # Remove file so a fresh token is generated
        token_file.unlink()

        # Second generation on the SAME hardware must produce a DIFFERENT random token
        # (proving it does NOT derive deterministically from machine_id)
        token_2 = get_or_create_node_auth_token(search_paths=[token_file])
        self.assertTrue(token_2.startswith("cm_tunnel_"))
        self.assertGreaterEqual(len(token_2), 10 + 48)
        self.assertNotEqual(token_1, token_2, "Tokens must be freshly randomized, not deterministic hardware hashes")

    def test_negative_security_hardware_spoofing_rejected_with_401(self) -> None:
        """S1 Gate: Verify fail-closed security: an attacker sending matching hardware_id,
        matching GPUs, and even matching client IP, but WITHOUT a cryptographic signature,
        is strictly rejected with 401 Unauthorized.
        """
        now = datetime.now(timezone.utc)
        client_ip = "192.168.1.27"
        valid_token = "valid_initial_token_xyz"

        # Legitimate node registered with Ed25519 public key
        NODE_TELEMETRY_REGISTRY[self.node_id] = {
            "node_id": self.node_id,
            "auth_token": valid_token,
            "public_key": self.node_public_key_hex,
            "owner_id": self.owner_id,
            "client_ip": client_ip,
            "inventory": {
                "gpus": [{"vendor": "amd", "model_name": "AMD Radeon RX 580", "vram_bytes": 8 * 1024**3, "healthy": True}]
            },
            "machine_identity": {"machine_id": "hw1:spoofed_target_machine_id_123"},
            "updated_at": (now - timedelta(seconds=400)).isoformat().replace("+00:00", "Z"), # stale
        }
        gateway_server.OWNER_ACCOUNT_STORE.bind_provider_node(self.owner_id, self.node_id)

        # Attacker crafts payload copying all hardware attributes + IP but lacks private key
        attacker_payload = {
            "node_id": self.node_id,
            "auth_token": "attacker_new_token_attempt",
            "inventory": {
                "gpus": [{"vendor": "amd", "model_name": "AMD Radeon RX 580", "vram_bytes": 8 * 1024**3, "healthy": True}]
            },
            "machine_identity": {"machine_id": "hw1:spoofed_target_machine_id_123"},
            # Notice: NO signature and NO valid proof
        }

        server = ThreadingHTTPServer(("127.0.0.1", 0), GatewayHandler)
        server_port = server.server_address[1]
        server_thread = threading.Thread(target=server.serve_forever, daemon=True)
        server_thread.start()

        try:
            req = urllib.request.Request(
                f"http://127.0.0.1:{server_port}/api/v1/node/heartbeat",
                data=json.dumps(attacker_payload).encode("utf-8"),
                headers={"Content-Type": "application/json", "X-Forwarded-For": client_ip},
            )
            with self.assertRaises(urllib.error.HTTPError) as ctx:
                urllib.request.urlopen(req, timeout=5)
            self.assertEqual(ctx.exception.code, 401, "Hardware spoofing without cryptographic signature must be 401 Unauthorized")

        finally:
            server.shutdown()
            server.server_close()

    def test_negative_security_mismatched_public_key_rejected_with_401(self) -> None:
        """S5 Gate: Verify that an attacker presenting an Ed25519 signature from a DIFFERENT,
        unregistered keypair is rejected with 401 Unauthorized.
        """
        now = datetime.now(timezone.utc)
        client_ip = "192.168.1.27"
        valid_token = "valid_initial_token_xyz"

        NODE_TELEMETRY_REGISTRY[self.node_id] = {
            "node_id": self.node_id,
            "auth_token": valid_token,
            "public_key": self.node_public_key_hex,
            "owner_id": self.owner_id,
            "client_ip": client_ip,
            "updated_at": (now - timedelta(seconds=400)).isoformat().replace("+00:00", "Z"),
        }

        # Attacker keypair
        attacker_key = Ed25519PrivateKey.generate()
        attacker_pub_bytes = attacker_key.public_key().public_bytes(
            serialization.Encoding.Raw, serialization.PublicFormat.Raw
        )
        attacker_token = "attacker_token_hijack"
        now_ts = int(time.time())
        attacker_nonce = "mismatched-key-nonce"
        attacker_sig = sign_node_heartbeat(
            attacker_key,
            self.node_id,
            attacker_token,
            now_ts,
            nonce=attacker_nonce,
        )

        attacker_payload = {
            "node_id": self.node_id,
            "auth_token": attacker_token,
            "public_key": attacker_pub_bytes.hex(),
            "signature": attacker_sig,
            "timestamp": now_ts,
            "nonce": attacker_nonce,
        }

        server = ThreadingHTTPServer(("127.0.0.1", 0), GatewayHandler)
        server_port = server.server_address[1]
        server_thread = threading.Thread(target=server.serve_forever, daemon=True)
        server_thread.start()

        try:
            req = urllib.request.Request(
                f"http://127.0.0.1:{server_port}/api/v1/node/heartbeat",
                data=json.dumps(attacker_payload).encode("utf-8"),
                headers={"Content-Type": "application/json", "X-Forwarded-For": client_ip},
            )
            with self.assertRaises(urllib.error.HTTPError) as ctx:
                urllib.request.urlopen(req, timeout=5)
            self.assertEqual(ctx.exception.code, 401, "Mismatched key signature must be rejected with 401")

        finally:
            server.shutdown()
            server.server_close()

    def test_negative_security_legacy_node_cannot_bind_attacker_key(self) -> None:
        """A legacy node without a stored key must not accept a caller-supplied key."""
        now = datetime.now(timezone.utc)
        client_ip = "192.168.1.27"
        legacy_token = "legacy_token_still_registered"
        NODE_TELEMETRY_REGISTRY[self.node_id] = {
            "node_id": self.node_id,
            "auth_token": legacy_token,
            "owner_id": self.owner_id,
            "client_ip": client_ip,
            "updated_at": (now - timedelta(seconds=400)).isoformat().replace("+00:00", "Z"),
        }

        attacker_key = Ed25519PrivateKey.generate()
        attacker_token = "attacker_token_for_legacy_takeover"
        now_ts = int(time.time())
        attacker_nonce = "legacy-takeover-nonce"
        attacker_public_key = attacker_key.public_key().public_bytes(
            serialization.Encoding.Raw,
            serialization.PublicFormat.Raw,
        ).hex()
        attacker_signature = sign_node_heartbeat(
            attacker_key,
            self.node_id,
            attacker_token,
            now_ts,
            nonce=attacker_nonce,
        )
        attacker_payload = {
            "node_id": self.node_id,
            "auth_token": attacker_token,
            "public_key": attacker_public_key,
            "signature": attacker_signature,
            "timestamp": now_ts,
            "nonce": attacker_nonce,
        }

        server = ThreadingHTTPServer(("127.0.0.1", 0), GatewayHandler)
        server_port = server.server_address[1]
        server_thread = threading.Thread(target=server.serve_forever, daemon=True)
        server_thread.start()

        try:
            req = urllib.request.Request(
                f"http://127.0.0.1:{server_port}/api/v1/node/heartbeat",
                data=json.dumps(attacker_payload).encode("utf-8"),
                headers={"Content-Type": "application/json", "X-Forwarded-For": client_ip},
            )
            with self.assertRaises(urllib.error.HTTPError) as ctx:
                urllib.request.urlopen(req, timeout=5)
            self.assertEqual(ctx.exception.code, 401)
            self.assertEqual(
                NODE_TELEMETRY_REGISTRY[self.node_id]["auth_token"],
                legacy_token,
            )
            self.assertNotEqual(
                NODE_TELEMETRY_REGISTRY[self.node_id].get("public_key", ""),
                attacker_public_key,
            )
        finally:
            server.shutdown()
            server.server_close()

    def test_negative_security_replayed_expired_timestamp_rejected_with_401(self) -> None:
        """Verify anti-replay protection: a valid signature with an expired timestamp (>60s)
        is rejected with 401 Unauthorized.
        """
        now = datetime.now(timezone.utc)
        client_ip = "192.168.1.27"
        valid_token = "valid_initial_token_xyz"

        NODE_TELEMETRY_REGISTRY[self.node_id] = {
            "node_id": self.node_id,
            "auth_token": valid_token,
            "public_key": self.node_public_key_hex,
            "owner_id": self.owner_id,
            "client_ip": client_ip,
            "updated_at": (now - timedelta(seconds=400)).isoformat().replace("+00:00", "Z"),
        }

        # Timestamp 300 seconds in the past
        expired_ts = int(time.time()) - 300
        new_token = "replayed_token_attempt"
        expired_nonce = "expired-heartbeat-nonce"
        expired_sig = sign_node_heartbeat(
            self.node_private_key,
            self.node_id,
            new_token,
            expired_ts,
            nonce=expired_nonce,
        )

        replay_payload = {
            "node_id": self.node_id,
            "auth_token": new_token,
            "public_key": self.node_public_key_hex,
            "signature": expired_sig,
            "timestamp": expired_ts,
            "nonce": expired_nonce,
        }

        server = ThreadingHTTPServer(("127.0.0.1", 0), GatewayHandler)
        server_port = server.server_address[1]
        server_thread = threading.Thread(target=server.serve_forever, daemon=True)
        server_thread.start()

        try:
            req = urllib.request.Request(
                f"http://127.0.0.1:{server_port}/api/v1/node/heartbeat",
                data=json.dumps(replay_payload).encode("utf-8"),
                headers={"Content-Type": "application/json", "X-Forwarded-For": client_ip},
            )
            with self.assertRaises(urllib.error.HTTPError) as ctx:
                urllib.request.urlopen(req, timeout=5)
            self.assertEqual(ctx.exception.code, 401, "Replayed expired timestamp must be rejected with 401")

        finally:
            server.shutdown()
            server.server_close()

    def test_negative_security_parallel_replay_of_same_heartbeat_nonce_rejected(self) -> None:
        """Only one concurrent request may consume a signed heartbeat nonce."""
        old_token = "parallel-old-token"
        new_token = "parallel-new-token"
        nonce = "parallel-single-use-nonce"
        NODE_TELEMETRY_REGISTRY[self.node_id] = {
            "node_id": self.node_id,
            "auth_token": old_token,
            "public_key": self.node_public_key_hex,
            "owner_id": self.owner_id,
            "updated_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        }
        timestamp = int(time.time())
        payload = {
            "node_id": self.node_id,
            "auth_token": new_token,
            "public_key": self.node_public_key_hex,
            "signature": sign_node_heartbeat(
                self.node_private_key,
                self.node_id,
                new_token,
                timestamp,
                nonce=nonce,
            ),
            "timestamp": timestamp,
            "nonce": nonce,
        }

        server = ThreadingHTTPServer(("127.0.0.1", 0), GatewayHandler)
        server_port = server.server_address[1]
        server_thread = threading.Thread(target=server.serve_forever, daemon=True)
        server_thread.start()

        def send_once() -> int:
            req = urllib.request.Request(
                f"http://127.0.0.1:{server_port}/api/v1/node/heartbeat",
                data=json.dumps(payload).encode("utf-8"),
                headers={"Content-Type": "application/json"},
            )
            try:
                with urllib.request.urlopen(req, timeout=5) as response:
                    return response.status
            except urllib.error.HTTPError as exc:
                return exc.code

        try:
            with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
                statuses = sorted(pool.map(lambda _item: send_once(), range(2)))
            self.assertEqual(statuses, [200, 401])
            self.assertEqual(NODE_TELEMETRY_REGISTRY[self.node_id]["auth_token"], new_token)
            self.assertIn(nonce, NODE_TELEMETRY_REGISTRY[self.node_id]["heartbeat_nonces"])
        finally:
            server.shutdown()
            server.server_close()

    def test_negative_security_token_cannot_reassign_existing_owner(self) -> None:
        """A valid node bearer token cannot silently move a node to another owner."""
        old_token = "owner-binding-token"
        other_owner_key = "cm_owner_other_fleet_local_test"
        NODE_TELEMETRY_REGISTRY[self.node_id] = {
            "node_id": self.node_id,
            "auth_token": old_token,
            "owner_id": self.owner_id,
            "updated_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        }

        server = ThreadingHTTPServer(("127.0.0.1", 0), GatewayHandler)
        server_port = server.server_address[1]
        server_thread = threading.Thread(target=server.serve_forever, daemon=True)
        server_thread.start()
        try:
            req = urllib.request.Request(
                f"http://127.0.0.1:{server_port}/api/v1/node/heartbeat",
                data=json.dumps(
                    {
                        "node_id": self.node_id,
                        "auth_token": old_token,
                        "owner_key": other_owner_key,
                    }
                ).encode("utf-8"),
                headers={"Content-Type": "application/json"},
            )
            with self.assertRaises(urllib.error.HTTPError) as ctx:
                urllib.request.urlopen(req, timeout=5)
            self.assertEqual(ctx.exception.code, 403)
            self.assertEqual(NODE_TELEMETRY_REGISTRY[self.node_id]["owner_id"], self.owner_id)
        finally:
            server.shutdown()
            server.server_close()

    def test_positive_ed25519_proof_of_possession_reconnect_accepted(self) -> None:
        """S4/R1 Gate: Verify that a legitimate node reconnecting after a reboot with a new token
        is admitted upon presenting a valid Ed25519 cryptographic proof of possession.
        """
        now = datetime.now(timezone.utc)
        client_ip = "192.168.1.27"
        old_token = "pre_reboot_token_111"

        gpu_inventory = {
            "total_vram_bytes": 48 * 1024**3,
            "gpus": [
                {"vendor": "amd", "model_name": "AMD Radeon RX 580", "vram_bytes": 8 * 1024**3, "healthy": True}
                for _ in range(6)
            ],
        }

        # 1. Registered node in telemetry registry with registered public key
        NODE_TELEMETRY_REGISTRY[self.node_id] = {
            "node_id": self.node_id,
            "auth_token": old_token,
            "public_key": self.node_public_key_hex,
            "owner_id": self.owner_id,
            "client_ip": client_ip,
            "inventory": gpu_inventory,
            "updated_at": (now - timedelta(seconds=400)).isoformat().replace("+00:00", "Z"), # stale
        }
        gateway_server.OWNER_ACCOUNT_STORE.bind_provider_node(self.owner_id, self.node_id)

        # Confirm initial fleet status is offline
        initial_fleet = _build_fleet_payload(self.owner_id)
        node_entry = next(n for n in initial_fleet["nodes"] if n["node_id"] == self.node_id)
        self.assertEqual(node_entry["status"], "offline")
        self.assertFalse(node_entry["is_online"])

        # 2. Node reboots: presents new token, signed with its persistent Ed25519 private key
        new_token = "post_reboot_random_token_222"
        now_ts = int(time.time())
        reconnect_nonce = "reconnect-heartbeat-nonce"
        sig_b64u = sign_node_heartbeat(
            self.node_private_key,
            self.node_id,
            new_token,
            now_ts,
            nonce=reconnect_nonce,
        )

        reconnect_body = {
            "node_id": self.node_id,
            "auth_token": new_token,
            "owner_key": "", # No owner_key needed; authenticated by Ed25519 possession proof!
            "public_key": self.node_public_key_hex,
            "signature": sig_b64u,
            "timestamp": now_ts,
            "nonce": reconnect_nonce,
            "inventory": gpu_inventory,
            "telemetry": {"tokens_processed": 50},
        }

        server = ThreadingHTTPServer(("127.0.0.1", 0), GatewayHandler)
        server_port = server.server_address[1]
        server_thread = threading.Thread(target=server.serve_forever, daemon=True)
        server_thread.start()

        try:
            req = urllib.request.Request(
                f"http://127.0.0.1:{server_port}/api/v1/node/heartbeat",
                data=json.dumps(reconnect_body).encode("utf-8"),
                headers={"Content-Type": "application/json", "X-Forwarded-For": client_ip},
            )
            with urllib.request.urlopen(req, timeout=5) as resp:
                self.assertEqual(resp.status, 200)
                data = json.loads(resp.read().decode("utf-8"))
                self.assertEqual(data.get("status"), "ok")

            # Verify registry updated token and maintained ownership
            updated_node = NODE_TELEMETRY_REGISTRY[self.node_id]
            self.assertEqual(updated_node["auth_token"], new_token)
            self.assertEqual(updated_node["owner_id"], self.owner_id)
            self.assertEqual(updated_node["public_key"], self.node_public_key_hex)

            # Verify fleet view reports ONLINE
            fleet_after = _build_fleet_payload(self.owner_id)
            node_after = next(n for n in fleet_after["nodes"] if n["node_id"] == self.node_id)
            self.assertEqual(node_after["status"], "online")
            self.assertTrue(node_after["is_online"])

        finally:
            server.shutdown()
            server.server_close()

    def test_ten_consecutive_reboots_with_cryptographic_possession(self) -> None:
        """R2 Gate: Verify 10 consecutive reboots using genuine Ed25519 proofs of possession.
        Ensures:
        - No phantom duplicate nodes are created (exactly 1 registry entry).
        - Fleet ownership (owner_id) is permanently retained.
        - Node successfully transitions to ONLINE on every single reboot.
        """
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
            # 1. Initial registration with public key
            initial_token = "initial_token_genesis"
            now_ts = int(time.time())
            initial_nonce = "initial-heartbeat-nonce"
            initial_sig = sign_node_heartbeat(
                self.node_private_key,
                self.node_id,
                initial_token,
                now_ts,
                nonce=initial_nonce,
            )
            init_body = {
                "node_id": self.node_id,
                "auth_token": initial_token,
                "owner_key": self.owner_key,
                "public_key": self.node_public_key_hex,
                "signature": initial_sig,
                "timestamp": now_ts,
                "nonce": initial_nonce,
                "inventory": gpu_inv,
            }
            req = urllib.request.Request(
                f"http://127.0.0.1:{server_port}/api/v1/node/heartbeat",
                data=json.dumps(init_body).encode("utf-8"),
                headers={"Content-Type": "application/json", "X-Forwarded-For": client_ip},
            )
            with urllib.request.urlopen(req, timeout=5) as resp:
                self.assertEqual(resp.status, 200)

            # 2. Run 10 Consecutive Reboots
            for cycle in range(1, 11):
                # Simulate node being offline past the 300s stale timeout
                NODE_TELEMETRY_REGISTRY[self.node_id]["updated_at"] = (
                    datetime.now(timezone.utc) - timedelta(seconds=350)
                ).isoformat().replace("+00:00", "Z")

                # Verify offline status
                fleet_stale = _build_fleet_payload(self.owner_id)
                n_stale = next(n for n in fleet_stale["nodes"] if n["node_id"] == self.node_id)
                self.assertEqual(n_stale["status"], "offline")

                # Node reboots: generates new high-entropy token and signs with persistent Ed25519 key
                cycle_token = f"cycle_token_{cycle}_{int(time.time())}"
                cycle_ts = int(time.time())
                cycle_nonce = f"cycle-heartbeat-nonce-{cycle}"
                cycle_sig = sign_node_heartbeat(
                    self.node_private_key,
                    self.node_id,
                    cycle_token,
                    cycle_ts,
                    nonce=cycle_nonce,
                )

                heartbeat_payload = {
                    "node_id": self.node_id,
                    "auth_token": cycle_token,
                    "public_key": self.node_public_key_hex,
                    "signature": cycle_sig,
                    "timestamp": cycle_ts,
                    "nonce": cycle_nonce,
                    "inventory": gpu_inv,
                }
                hb_req = urllib.request.Request(
                    f"http://127.0.0.1:{server_port}/api/v1/node/heartbeat",
                    data=json.dumps(heartbeat_payload).encode("utf-8"),
                    headers={"Content-Type": "application/json", "X-Forwarded-For": client_ip},
                )
                with urllib.request.urlopen(hb_req, timeout=5) as hb_resp:
                    self.assertEqual(hb_resp.status, 200)

                # Verify status is ONLINE and owner_id is maintained
                fleet_live = _build_fleet_payload(self.owner_id)
                n_live = next(n for n in fleet_live["nodes"] if n["node_id"] == self.node_id)
                self.assertEqual(n_live["status"], "online", f"Node must be online on cycle {cycle}")
                self.assertTrue(n_live["is_online"])
                self.assertEqual(NODE_TELEMETRY_REGISTRY[self.node_id]["owner_id"], self.owner_id)
                self.assertEqual(NODE_TELEMETRY_REGISTRY[self.node_id]["auth_token"], cycle_token)

            # Invariant: exactly 1 entry exists in registry, zero phantom duplicates
            self.assertEqual(len(NODE_TELEMETRY_REGISTRY), 1)

        finally:
            server.shutdown()
            server.server_close()


if __name__ == "__main__":
    unittest.main()
