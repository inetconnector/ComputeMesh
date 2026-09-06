"""Unit tests for the passkey fleet-account SQLite store."""
from datetime import datetime, timedelta, timezone
from pathlib import Path
import tempfile
import unittest

from services.portal.fleet_accounts import FleetAccountStore, FleetAccountStoreError


class TestFleetAccountStore(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp_dir = tempfile.TemporaryDirectory()
        self.store = FleetAccountStore(Path(self.tmp_dir.name) / "fleet.db")

    def tearDown(self) -> None:
        self.tmp_dir.cleanup()

    def test_create_account_generates_unique_owner_key(self) -> None:
        acc1 = self.store.create_account("alice@example.com")
        acc2 = self.store.create_account("bob@example.com")
        self.assertTrue(acc1.owner_key)
        self.assertNotEqual(acc1.owner_key, acc2.owner_key)
        self.assertNotEqual(acc1.account_id, acc2.account_id)

    def test_duplicate_email_rejected(self) -> None:
        self.store.create_account("alice@example.com")
        with self.assertRaises(FleetAccountStoreError):
            self.store.create_account("alice@example.com")

    def test_get_account_by_email_case_insensitive(self) -> None:
        created = self.store.create_account("Alice@Example.com")
        found = self.store.get_account_by_email("alice@example.com")
        self.assertIsNotNone(found)
        self.assertEqual(found.account_id, created.account_id)

    def test_get_account_by_email_unknown_returns_none(self) -> None:
        self.assertIsNone(self.store.get_account_by_email("nobody@example.com"))

    def test_passkey_roundtrip(self) -> None:
        acc = self.store.create_account("alice@example.com")
        self.store.add_passkey(acc.account_id, "cred_1", "pubkey_b64", 0, "internal")
        pk = self.store.get_passkey("cred_1")
        self.assertIsNotNone(pk)
        self.assertEqual(pk.account_id, acc.account_id)
        self.assertEqual(pk.sign_count, 0)

        self.store.update_sign_count("cred_1", 5)
        pk2 = self.store.get_passkey("cred_1")
        self.assertEqual(pk2.sign_count, 5)

        keys = self.store.list_passkeys(acc.account_id)
        self.assertEqual(len(keys), 1)

    def test_duplicate_credential_id_rejected(self) -> None:
        acc = self.store.create_account("alice@example.com")
        self.store.add_passkey(acc.account_id, "cred_1", "pubkey", 0, "")
        with self.assertRaises(FleetAccountStoreError):
            self.store.add_passkey(acc.account_id, "cred_1", "other_pubkey", 0, "")

    def test_challenge_consume_once(self) -> None:
        self.store.store_challenge("alice@example.com", "registration", "chal_b64")
        got = self.store.consume_challenge("alice@example.com", "registration")
        self.assertEqual(got, "chal_b64")
        # consuming again returns None -- the challenge was deleted
        self.assertIsNone(self.store.consume_challenge("alice@example.com", "registration"))

    def test_challenge_expired_returns_none(self) -> None:
        self.store.store_challenge("alice@example.com", "registration", "chal_b64")
        with self.store._connection() as conn:
            past = (datetime.now(timezone.utc) - timedelta(minutes=1)).isoformat().replace("+00:00", "Z")
            conn.execute(
                "UPDATE fleet_challenges SET expires_at = ? WHERE email = ? AND kind = ?",
                (past, "alice@example.com", "registration"),
            )
        self.assertIsNone(self.store.consume_challenge("alice@example.com", "registration"))

    def test_session_roundtrip_and_logout(self) -> None:
        acc = self.store.create_account("alice@example.com")
        token = self.store.create_session(acc.account_id)
        resolved = self.store.get_session_account(token)
        self.assertIsNotNone(resolved)
        self.assertEqual(resolved.account_id, acc.account_id)

        self.store.delete_session(token)
        self.assertIsNone(self.store.get_session_account(token))

    def test_expired_session_rejected(self) -> None:
        acc = self.store.create_account("alice@example.com")
        token = self.store.create_session(acc.account_id)
        with self.store._connection() as conn:
            past = (datetime.now(timezone.utc) - timedelta(days=1)).isoformat().replace("+00:00", "Z")
            conn.execute("UPDATE fleet_sessions SET expires_at = ? WHERE session_token = ?", (past, token))
        self.assertIsNone(self.store.get_session_account(token))

    def test_unknown_session_token_returns_none(self) -> None:
        self.assertIsNone(self.store.get_session_account("does-not-exist"))

    def test_owner_key_format_and_rotation(self) -> None:
        acc = self.store.create_account("charlie@example.com")
        self.assertTrue(acc.owner_key.startswith("inet-"))
        self.assertGreaterEqual(len(acc.owner_key), 24)

        # Rotate without proposed key generates a new unique inet- key
        old_key = acc.owner_key
        new_key = self.store.rotate_owner_key(acc.account_id)
        self.assertTrue(new_key.startswith("inet-"))
        self.assertNotEqual(old_key, new_key)
        self.assertEqual(self.store.get_account(acc.account_id).owner_key, new_key)

    def test_owner_key_custom_validation_and_uniqueness(self) -> None:
        acc1 = self.store.create_account("user1@example.com")
        acc2 = self.store.create_account("user2@example.com")

        # Must start with inet-
        with self.assertRaises(FleetAccountStoreError):
            self.store.rotate_owner_key(acc1.account_id, "invalid-prefix-12345678901234567890")

        # Must be at least 24 chars
        with self.assertRaises(FleetAccountStoreError):
            self.store.rotate_owner_key(acc1.account_id, "inet-tooshort")

        # Must not contain dangerous/illegal characters
        with self.assertRaises(FleetAccountStoreError):
            self.store.rotate_owner_key(acc1.account_id, "inet-bad char's;drop table 12345")

        # Valid custom inet- key
        custom_key = "inet-custom-production-key-998877665544332211"
        rotated = self.store.rotate_owner_key(acc1.account_id, custom_key)
        self.assertEqual(rotated, custom_key)
        self.assertEqual(self.store.get_account_by_owner_key(custom_key).account_id, acc1.account_id)

        # Rejects if already in use by another user (acc1)
        with self.assertRaises(FleetAccountStoreError):
            self.store.rotate_owner_key(acc2.account_id, custom_key)


if __name__ == "__main__":
    unittest.main()
