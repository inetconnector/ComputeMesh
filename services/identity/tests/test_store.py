from datetime import datetime, timedelta, timezone
import tempfile
import unittest
from pathlib import Path

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from services.identity.store import (
    EnrollmentConflict,
    EnrollmentTokenExpired,
    IdentityAuthorizationError,
    SQLiteIdentityStore,
)


def pubkey():
    return Ed25519PrivateKey.generate().public_key().public_bytes(
        serialization.Encoding.Raw, serialization.PublicFormat.Raw
    )


class IdentityStoreTests(unittest.TestCase):
    def setUp(self):
        self.now = datetime(2026, 8, 21, 19, 0, tzinfo=timezone.utc)
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / "identity.db"
        self.store = SQLiteIdentityStore(self.path)

    def tearDown(self):
        self.store.close()
        self.tmp.cleanup()

    def token(self, *, expires=None):
        return self.store.create_enrollment_token(
            "provider-1",
            expires_at=expires or self.now + timedelta(minutes=5),
            now=self.now,
        )

    def test_enrollment_is_idempotent_for_same_token_and_key(self):
        token = self.token()
        key = pubkey()
        first = self.store.enroll(token, key, now=self.now)
        second = self.store.enroll(token, key, now=self.now + timedelta(seconds=1))
        self.assertTrue(first.created)
        self.assertFalse(second.created)
        self.assertEqual(first.node_id, second.node_id)
        self.assertEqual(first.key_id, second.key_id)
        self.assertEqual(
            self.store.resolve_key(first.node_id, first.key_id).public_key, key
        )

    def test_consumed_token_cannot_bind_different_key(self):
        token = self.token()
        self.store.enroll(token, pubkey(), now=self.now)
        with self.assertRaises(EnrollmentConflict):
            self.store.enroll(token, pubkey(), now=self.now)

    def test_same_public_key_cannot_enroll_second_node(self):
        key = pubkey()
        self.store.enroll(self.token(), key, now=self.now)
        with self.assertRaises(EnrollmentConflict):
            self.store.enroll(self.token(), key, now=self.now)

    def test_expired_token_rejected(self):
        token = self.token(expires=self.now + timedelta(seconds=1))
        with self.assertRaises(EnrollmentTokenExpired):
            self.store.enroll(token, pubkey(), now=self.now + timedelta(seconds=2))

    def test_rotation_preserves_node_id_and_revokes_old_key(self):
        first_key = pubkey()
        enrolled = self.store.enroll(self.token(), first_key, now=self.now)
        second_key = pubkey()
        rotated = self.store.rotate_key(
            enrolled.node_id,
            "provider-1",
            second_key,
            now=self.now + timedelta(minutes=1),
        )
        self.assertEqual(rotated.node_id, enrolled.node_id)
        with self.assertRaises(KeyError):
            self.store.resolve_key(enrolled.node_id, enrolled.key_id)
        self.assertEqual(
            self.store.resolve_key(enrolled.node_id, rotated.key_id).public_key,
            second_key,
        )

    def test_revoke_key_blocks_resolver(self):
        enrolled = self.store.enroll(self.token(), pubkey(), now=self.now)
        state = self.store.revoke_key(
            enrolled.node_id,
            "provider-1",
            enrolled.key_id,
            now=self.now + timedelta(minutes=1),
        )
        self.assertEqual(state.status, "revoked")
        with self.assertRaises(KeyError):
            self.store.resolve_key(enrolled.node_id, enrolled.key_id)

    def test_revoke_node_blocks_all_keys(self):
        enrolled = self.store.enroll(self.token(), pubkey(), now=self.now)
        rotated = self.store.rotate_key(
            enrolled.node_id,
            "provider-1",
            pubkey(),
            revoke_previous=False,
            now=self.now + timedelta(seconds=10),
        )
        self.store.revoke_node(
            enrolled.node_id,
            "provider-1",
            now=self.now + timedelta(minutes=1),
        )
        for key_id in (enrolled.key_id, rotated.key_id):
            with self.assertRaises(KeyError):
                self.store.resolve_key(enrolled.node_id, key_id)

    def test_wrong_principal_cannot_rotate_or_revoke(self):
        enrolled = self.store.enroll(self.token(), pubkey(), now=self.now)
        with self.assertRaises(IdentityAuthorizationError):
            self.store.rotate_key(enrolled.node_id, "provider-other", pubkey(), now=self.now)
        with self.assertRaises(IdentityAuthorizationError):
            self.store.revoke_key(
                enrolled.node_id, "provider-other", enrolled.key_id, now=self.now
            )

    def test_revoked_key_cannot_be_reactivated_by_rotation(self):
        enrolled = self.store.enroll(self.token(), pubkey(), now=self.now)
        original_public = self.store.resolve_key(
            enrolled.node_id, enrolled.key_id
        ).public_key
        self.store.revoke_key(
            enrolled.node_id,
            "provider-1",
            enrolled.key_id,
            now=self.now + timedelta(seconds=5),
        )
        with self.assertRaises(EnrollmentConflict):
            self.store.rotate_key(
                enrolled.node_id,
                "provider-1",
                original_public,
                now=self.now + timedelta(seconds=10),
            )

    def test_enrollment_token_ttl_is_bounded(self):
        with self.assertRaises(ValueError):
            self.store.create_enrollment_token(
                "provider-1",
                expires_at=self.now + timedelta(minutes=16),
                now=self.now,
            )

    def test_enrollment_times_must_be_timezone_aware(self):
        with self.assertRaises(ValueError):
            self.store.create_enrollment_token(
                "provider-1",
                expires_at=datetime(2026, 8, 21, 19, 5),
                now=self.now,
            )

    def test_state_survives_restart(self):
        enrolled = self.store.enroll(self.token(), pubkey(), now=self.now)
        self.store.close()
        self.store = SQLiteIdentityStore(self.path)
        resolved = self.store.resolve_key(enrolled.node_id, enrolled.key_id)
        self.assertEqual(resolved.node_id, enrolled.node_id)


if __name__ == "__main__":
    unittest.main()
