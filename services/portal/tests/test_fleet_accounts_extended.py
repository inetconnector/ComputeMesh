"""Unit tests for the extended fleet account store with magic links and multi-passkeys."""
from pathlib import Path
import tempfile
import unittest

from services.portal.fleet_accounts import FleetAccountStore, FleetAccountStoreError


class TestFleetAccountsExtended(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp_dir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.tmp_dir.name) / "fleet.db"
        self.store = FleetAccountStore(self.db_path)

    def tearDown(self) -> None:
        self.tmp_dir.cleanup()

    def test_magic_link_token_lifecycle(self) -> None:
        email = "owner@inetconnector.com"
        raw_token = self.store.create_magic_link_token(email, ttl_minutes=15)
        self.assertTrue(len(raw_token) > 20)

        # First verification succeeds and provisions or returns account
        account = self.store.verify_magic_link_token(raw_token)
        self.assertIsNotNone(account)
        self.assertEqual(account.email, email)
        self.assertTrue(account.owner_key.startswith("ok_"))

        # Second verification fails (single-use)
        second_try = self.store.verify_magic_link_token(raw_token)
        self.assertIsNone(second_try)

    def test_multi_passkey_management(self) -> None:
        account = self.store.create_account("admin@inetconnector.com")
        self.store.add_passkey(account.account_id, "cred_1", "pubkey_1", 0, "internal", nickname="MacBook")
        self.store.add_passkey(account.account_id, "cred_2", "pubkey_2", 0, "usb", nickname="YubiKey")

        keys = self.store.list_passkeys(account.account_id)
        self.assertEqual(len(keys), 2)
        self.assertEqual(keys[0].nickname, "MacBook")
        self.assertEqual(keys[1].nickname, "YubiKey")

        # Rename
        renamed = self.store.rename_passkey(account.account_id, "cred_2", "YubiKey 5C")
        self.assertTrue(renamed)
        keys_after_rename = self.store.list_passkeys(account.account_id)
        self.assertEqual(keys_after_rename[1].nickname, "YubiKey 5C")

        # Delete
        deleted = self.store.delete_passkey(account.account_id, "cred_1")
        self.assertTrue(deleted)
        keys_after_delete = self.store.list_passkeys(account.account_id)
        self.assertEqual(len(keys_after_delete), 1)

    def test_enrollment_token_verification(self) -> None:
        account = self.store.create_account("rigs@inetconnector.com")
        token = self.store.create_enrollment_token(account.account_id, ttl_minutes=30)
        self.assertTrue(token.startswith("cmenroll_"))

        owner_key = self.store.verify_and_consume_enrollment_token(token)
        self.assertEqual(owner_key, account.owner_key)

        # Single-use consumption
        self.assertIsNone(self.store.verify_and_consume_enrollment_token(token))

    def test_audit_log(self) -> None:
        account = self.store.create_account("audited@inetconnector.com")
        self.store.record_audit_event(
            account.account_id, account.email, "login_success", "Passkey login", "127.0.0.1", "Chrome"
        )
        logs = self.store.get_audit_log(account.account_id)
        self.assertEqual(len(logs), 1)
        self.assertEqual(logs[0]["event_type"], "login_success")
        self.assertEqual(logs[0]["ip_address"], "127.0.0.1")


if __name__ == "__main__":
    unittest.main()
