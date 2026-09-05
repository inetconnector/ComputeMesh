"""Unit tests for mail dispatcher and extended passkey / magic link HTTP routes."""
from http import HTTPStatus
from pathlib import Path
import tempfile
from typing import Any
import unittest
from unittest.mock import patch

from services.portal import mail_dispatcher, passkey_routes
from services.portal.fleet_accounts import FleetAccountStore


class TestMailAndRoutesExtended(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp_dir = tempfile.TemporaryDirectory()
        self.store = FleetAccountStore(Path(self.tmp_dir.name) / "fleet.db")
        self.original_store = passkey_routes.FLEET_ACCOUNT_STORE
        passkey_routes.FLEET_ACCOUNT_STORE = self.store
        self.handler = passkey_routes.PasskeyAuthHandler()

    def tearDown(self) -> None:
        passkey_routes.FLEET_ACCOUNT_STORE = self.original_store
        self.tmp_dir.cleanup()

    @patch("services.portal.passkey_routes.send_security_alert", return_value=True)
    @patch("services.portal.passkey_routes.send_magic_link", return_value=True)
    def test_magic_link_request_and_verify(self, mock_send: Any, mock_alert: Any) -> None:
        email = "testowner@inetconnector.com"
        res, status, _ = self.handler.request_magic_link({"email": email})
        self.assertEqual(status, HTTPStatus.OK)
        self.assertEqual(res["status"], "ok")
        self.assertTrue(mock_send.called)

        # Retrieve the generated token from store
        with self.store._connection() as conn:
            row = conn.execute("SELECT * FROM fleet_recovery_tokens WHERE email = ?", (email,)).fetchone()
            self.assertIsNotNone(row)

        # Find raw token generated or create one to test verification
        raw_token = self.store.create_magic_link_token(email)
        ver_res, ver_status, cookie = self.handler.verify_magic_link({"magic_token": raw_token})
        self.assertEqual(ver_status, HTTPStatus.OK)
        self.assertEqual(ver_res["email"], email)
        self.assertIn(passkey_routes.SESSION_COOKIE_NAME, cookie)

    def test_passkey_management_routes(self) -> None:
        account = self.store.create_account("multi@inetconnector.com")
        self.store.add_passkey(account.account_id, "cred_a", "pk_a", 0, "", nickname="Key A")
        self.store.add_passkey(account.account_id, "cred_b", "pk_b", 0, "", nickname="Key B")

        token = self.store.create_session(account.account_id)
        fake_headers = {"Cookie": f"{passkey_routes.SESSION_COOKIE_NAME}={token}"}

        # List passkeys
        list_res, list_status, _ = self.handler.list_passkeys(fake_headers)
        self.assertEqual(list_status, HTTPStatus.OK)
        self.assertEqual(len(list_res["passkeys"]), 2)

        # Rename passkey
        ren_res, ren_status, _ = self.handler.rename_passkey(fake_headers, {"credential_id": "cred_a", "nickname": "Laptop TouchID"})
        self.assertEqual(ren_status, HTTPStatus.OK)

        # Delete passkey
        del_res, del_status, _ = self.handler.delete_passkey(fake_headers, {"credential_id": "cred_a"})
        self.assertEqual(del_status, HTTPStatus.OK)

        # Remaining 1 passkey cannot be deleted
        del_last_res, del_last_status, _ = self.handler.delete_passkey(fake_headers, {"credential_id": "cred_b"})
        self.assertEqual(del_last_status, HTTPStatus.BAD_REQUEST)

    def test_enrollment_and_audit_routes(self) -> None:
        account = self.store.create_account("tokens@inetconnector.com")
        token = self.store.create_session(account.account_id)
        fake_headers = {"Cookie": f"{passkey_routes.SESSION_COOKIE_NAME}={token}"}

        # Create enrollment token
        enr_res, enr_status, _ = self.handler.create_enrollment_token(fake_headers)
        self.assertEqual(enr_status, HTTPStatus.OK)
        self.assertIn("cmenroll_", enr_res["enrollment_token"])

        # Audit log
        aud_res, aud_status, _ = self.handler.get_audit_log(fake_headers)
        self.assertEqual(aud_status, HTTPStatus.OK)
        self.assertIsInstance(aud_res["audit_log"], list)


if __name__ == "__main__":
    unittest.main()
