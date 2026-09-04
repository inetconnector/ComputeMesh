"""Unit tests for passkey registration/login route logic.

Actual WebAuthn signature/attestation cryptography is provided by the
third-party `webauthn` library and is not re-tested here; verify_* calls are
mocked so these tests focus on this module's own wiring: challenge
lifecycle, account/session creation, and error handling.
"""
from http import HTTPStatus
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from services.portal import passkey_routes
from services.portal.fleet_accounts import FleetAccountStore


class FakeVerifiedRegistration:
    def __init__(self, credential_id: bytes, public_key: bytes, sign_count: int = 0) -> None:
        self.credential_id = credential_id
        self.credential_public_key = public_key
        self.sign_count = sign_count


class FakeVerifiedAuthentication:
    def __init__(self, credential_id: bytes, new_sign_count: int) -> None:
        self.credential_id = credential_id
        self.new_sign_count = new_sign_count


class TestPasskeyAuthHandler(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp_dir = tempfile.TemporaryDirectory()
        self.original_store = passkey_routes.FLEET_ACCOUNT_STORE
        self.store = FleetAccountStore(Path(self.tmp_dir.name) / "fleet.db")
        passkey_routes.FLEET_ACCOUNT_STORE = self.store
        self.handler = passkey_routes.PasskeyAuthHandler()

    def tearDown(self) -> None:
        passkey_routes.FLEET_ACCOUNT_STORE = self.original_store
        self.tmp_dir.cleanup()

    def test_register_begin_missing_email(self) -> None:
        data, status, cookie = self.handler.register_begin({})
        self.assertEqual(status, HTTPStatus.BAD_REQUEST)
        self.assertIsNone(cookie)

    def test_register_begin_returns_options_and_stores_challenge(self) -> None:
        data, status, cookie = self.handler.register_begin({"email": "alice@example.com"})
        self.assertEqual(status, HTTPStatus.OK)
        self.assertIn("options", data)
        self.assertIsNone(cookie)
        # a pending challenge now exists for this email
        challenge = self.store.consume_challenge("alice@example.com", "registration")
        self.assertIsNotNone(challenge)

    def test_register_begin_rejects_existing_email(self) -> None:
        self.store.create_account("alice@example.com")
        data, status, cookie = self.handler.register_begin({"email": "alice@example.com"})
        self.assertEqual(status, HTTPStatus.CONFLICT)

    def test_register_complete_without_pending_challenge(self) -> None:
        data, status, cookie = self.handler.register_complete(
            {"email": "alice@example.com", "credential": {"id": "x"}}
        )
        self.assertEqual(status, HTTPStatus.BAD_REQUEST)

    @patch.object(passkey_routes.webauthn, "verify_registration_response")
    def test_register_complete_creates_account_and_session(self, mock_verify) -> None:
        self.handler.register_begin({"email": "alice@example.com"})
        mock_verify.return_value = FakeVerifiedRegistration(b"cred-id-bytes", b"pubkey-bytes")

        data, status, cookie = self.handler.register_complete(
            {"email": "alice@example.com", "credential": {"id": "Y3JlZC1pZC1ieXRlcw", "response": {}}}
        )
        self.assertEqual(status, HTTPStatus.CREATED)
        self.assertIn("owner_key", data)
        self.assertIsNotNone(cookie)
        self.assertIn(passkey_routes.SESSION_COOKIE_NAME, cookie)

        account = self.store.get_account_by_email("alice@example.com")
        self.assertIsNotNone(account)
        self.assertEqual(len(self.store.list_passkeys(account.account_id)), 1)

    def test_login_begin_unknown_email(self) -> None:
        data, status, cookie = self.handler.login_begin({"email": "nobody@example.com"})
        self.assertEqual(status, HTTPStatus.NOT_FOUND)

    def test_login_begin_no_passkeys(self) -> None:
        self.store.create_account("alice@example.com")
        data, status, cookie = self.handler.login_begin({"email": "alice@example.com"})
        self.assertEqual(status, HTTPStatus.NOT_FOUND)

    @patch.object(passkey_routes.webauthn, "verify_authentication_response")
    def test_login_complete_updates_sign_count_and_creates_session(self, mock_verify) -> None:
        acc = self.store.create_account("alice@example.com")
        cred_id_b64 = passkey_routes.bytes_to_base64url(b"cred-id-bytes")
        self.store.add_passkey(acc.account_id, cred_id_b64, "pubkey_b64", 3, "internal")

        self.handler.login_begin({"email": "alice@example.com"})
        mock_verify.return_value = FakeVerifiedAuthentication(b"cred-id-bytes", 4)

        data, status, cookie = self.handler.login_complete(
            {"email": "alice@example.com", "credential": {"id": cred_id_b64, "response": {}}}
        )
        self.assertEqual(status, HTTPStatus.OK)
        self.assertIsNotNone(cookie)
        pk = self.store.get_passkey(cred_id_b64)
        self.assertEqual(pk.sign_count, 4)

    def test_login_complete_unrecognized_credential(self) -> None:
        acc = self.store.create_account("alice@example.com")
        self.store.add_passkey(acc.account_id, "cred_known", "pubkey_b64", 0, "")
        self.handler.login_begin({"email": "alice@example.com"})

        data, status, cookie = self.handler.login_complete(
            {"email": "alice@example.com", "credential": {"id": "cred_unknown", "response": {}}}
        )
        self.assertEqual(status, HTTPStatus.UNAUTHORIZED)

    def test_logout_clears_session(self) -> None:
        acc = self.store.create_account("alice@example.com")
        token = self.store.create_session(acc.account_id)

        class FakeHeaders(dict):
            def get(self, key, default=""):
                return dict.get(self, key, default)

        headers = FakeHeaders({"Cookie": f"{passkey_routes.SESSION_COOKIE_NAME}={token}"})
        data, status, cookie = self.handler.logout(headers)
        self.assertEqual(status, HTTPStatus.OK)
        self.assertIsNone(self.store.get_session_account(token))


if __name__ == "__main__":
    unittest.main()
