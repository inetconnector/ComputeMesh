"""Fail-closed QR-only mobile enrollment and heartbeat regression tests.

No real keys, live API endpoints, or actual devices are used.
"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
import hashlib
from pathlib import Path
import tempfile
import time
import unittest

from services.portal.fleet_accounts import FleetAccountStore


class TestMobileDeviceCredentials(unittest.TestCase):
    def setUp(self) -> None:
        self.dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.dir.cleanup)
        self.store = FleetAccountStore(Path(self.dir.name) / "fleet.db")
        self.a = self.store.create_account("first@example.invalid")
        self.b = self.store.create_account("second@example.invalid")
        self.node = "android-testphone-000001"

    def issue(self, *, account=None, scope="mobile_device", ttl=30) -> str:
        return self.store.create_enrollment_token(
            (account or self.a).account_id, ttl_minutes=ttl, scope=scope
        )

    def test_mobile_qr_cannot_be_redeemed_as_nodeos_owner_key(self) -> None:
        token = self.issue()
        self.assertIsNone(self.store.verify_and_consume_enrollment_token(token))
        credential = self.store.consume_mobile_enrollment(token, self.node)
        self.assertRegex(credential, r"^cm_mobile_[a-f0-9]{64}$")
        self.assertNotEqual(credential, self.a.owner_key)
        self.assertIsNone(self.store.consume_mobile_enrollment(token, "android-next-000002"))

    def test_nodeos_scope_cannot_be_redeemed_by_mobile(self) -> None:
        token = self.issue(scope="legacy_node")
        self.assertIsNone(self.store.consume_mobile_enrollment(token, self.node))
        self.assertEqual(self.store.verify_and_consume_enrollment_token(token), self.a.owner_key)
        self.assertIsNone(self.store.verify_and_consume_enrollment_token(token))

    def test_mobile_token_is_hash_only_in_database_and_bound_to_node(self) -> None:
        token = self.issue()
        secret = self.store.consume_mobile_enrollment(token, self.node)
        with self.store._connection() as db:
            row = db.execute(
                "SELECT account_id, credential_sha256 FROM fleet_mobile_devices WHERE node_id=?",
                (self.node,),
            ).fetchone()
        self.assertEqual(row["account_id"], self.a.account_id)
        self.assertEqual(row["credential_sha256"], hashlib.sha256(secret.encode()).hexdigest())
        self.assertNotIn(secret, str(dict(row)))
        now = int(time.time())
        self.assertIsNone(self.store.authenticate_mobile_heartbeat("android-other-0", secret, "a"*32, now))
        self.assertIsNotNone(self.store.authenticate_mobile_heartbeat(self.node, secret, "b"*32, now))
        self.assertIsNone(self.store.authenticate_mobile_heartbeat(self.node, secret, "b"*32, now))

    def test_replay_stays_blocked_after_database_reopen(self) -> None:
        secret = self.store.consume_mobile_enrollment(self.issue(), self.node)
        now = int(time.time())
        self.assertIsNotNone(self.store.authenticate_mobile_heartbeat(self.node, secret, "nonce-reboot-0000001", now))
        reopened = FleetAccountStore(self.store.storage_path)
        self.assertIsNone(reopened.authenticate_mobile_heartbeat(self.node, secret, "nonce-reboot-0000001", now))
        self.assertIsNotNone(reopened.authenticate_mobile_heartbeat(self.node, secret, "nonce-reboot-0000002", now))

    def test_expiration_revocation_and_cross_tenant_denial(self) -> None:
        expired = self.issue()
        with self.store._connection() as db:
            db.execute(
                "UPDATE fleet_enrollment_tokens SET expires_at=? WHERE token=?",
                ((datetime.now(timezone.utc) - timedelta(minutes=2)).isoformat(), expired),
            )
        self.assertIsNone(self.store.consume_mobile_enrollment(expired, self.node))
        credential = self.store.consume_mobile_enrollment(self.issue(), self.node)
        now = int(time.time())
        self.assertIsNone(self.store.authenticate_mobile_heartbeat(self.node, credential, "a"*32, now - 300))
        self.assertIsNone(self.store.authenticate_mobile_heartbeat(self.node, credential, "a"*32, now + 300))
        self.assertFalse(self.store.revoke_mobile_device(self.b.account_id, self.node))
        self.assertIsNotNone(self.store.authenticate_mobile_heartbeat(self.node, credential, "a"*32, now))
        self.assertTrue(self.store.revoke_mobile_device(self.a.account_id, self.node))
        self.assertFalse(self.store.revoke_mobile_device(self.a.account_id, self.node))
        self.assertIsNone(self.store.authenticate_mobile_heartbeat(self.node, credential, "z"*32, now))
        # Revocation never allows a second QR to silently take over old ID.
        self.assertIsNone(self.store.consume_mobile_enrollment(self.issue(account=self.b), self.node))

    def test_one_qr_can_enroll_only_one_mobile_under_concurrency(self) -> None:
        qr = self.issue()
        node_ids = ["android-parallel-a0000", "android-parallel-b0000"]
        with ThreadPoolExecutor(max_workers=2) as executor:
            futures = [
                executor.submit(self.store.consume_mobile_enrollment, qr, node)
                for node in node_ids
            ]
            replies = [future.result() for future in futures]
        self.assertEqual(sum(value is not None for value in replies), 1)

    def test_malformed_claims_and_owner_key_never_validate(self) -> None:
        secret = self.store.consume_mobile_enrollment(self.issue(), self.node)
        now = int(time.time())
        self.assertIsNone(self.store.authenticate_mobile_heartbeat(self.node, self.a.owner_key, "a"*32, now))
        self.assertIsNone(self.store.authenticate_mobile_heartbeat(self.node, secret, "short", now))
        self.assertIsNone(self.store.authenticate_mobile_heartbeat(self.node, secret, "a"*32, True))
        self.assertIsNone(self.store.consume_mobile_enrollment(self.issue(), "windows-legacy-node"))


if __name__ == "__main__":
    unittest.main()
