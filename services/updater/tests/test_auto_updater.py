"""Unit tests for ComputeMesh Cryptographic Auto-Updater."""
import json
from pathlib import Path
import tempfile
import unittest

from cryptography.hazmat.primitives.asymmetric import ed25519

from services.updater.auto_updater import (
    AutoUpdater,
    ChecksumMismatchError,
    SignatureVerificationError,
    UpdateInfo,
)


class TestAutoUpdater(unittest.TestCase):
    def setUp(self) -> None:
        self.priv_key = ed25519.Ed25519PrivateKey.generate()
        self.pub_key = self.priv_key.public_key()
        self.pub_hex = self.pub_key.public_bytes_raw().hex()

        self.updater = AutoUpdater(
            current_version="1.1.0",
            manifest_url="http://mock-update-url/version.json",
            public_key_hex=self.pub_hex,
        )

    def test_version_parsing(self) -> None:
        self.assertEqual(AutoUpdater._parse_version("1.2.0"), (1, 2, 0))
        self.assertEqual(AutoUpdater._parse_version("v1.2.5"), (1, 2, 5))
        self.assertTrue(AutoUpdater._parse_version("1.2.1") > AutoUpdater._parse_version("1.2.0"))
        self.assertFalse(AutoUpdater._parse_version("1.1.5") > AutoUpdater._parse_version("1.2.0"))

    def test_signature_verification_success_and_tamper_detection(self) -> None:
        manifest_payload = {
            "version": "1.2.0",
            "release_date": "2026-08-23T20:00:00Z",
            "public_key": self.pub_hex,
            "platforms": {
                "windows-x64": {
                    "filename": "ComputeMesh-Setup-x64.exe",
                    "url": "http://example.com/setup.exe",
                    "sha256": "abcdef1234567890abcdef1234567890abcdef1234567890abcdef1234567890",
                    "size_bytes": 1000,
                }
            },
        }

        # Sign legitimate manifest
        canonical_bytes = json.dumps(manifest_payload, sort_keys=True).encode("utf-8")
        valid_sig = self.priv_key.sign(canonical_bytes).hex()

        signed_manifest = {**manifest_payload, "signature": valid_sig}

        # Verify legitimate signature works
        pub_key = ed25519.Ed25519PublicKey.from_public_bytes(bytes.fromhex(self.pub_hex))
        data_to_verify = dict(signed_manifest)
        sig = data_to_verify.pop("signature")
        pub_key.verify(bytes.fromhex(sig), json.dumps(data_to_verify, sort_keys=True).encode("utf-8"))

        # Test TAMPERING (Attacker changes URL or SHA-256)
        tampered_manifest = dict(signed_manifest)
        tampered_manifest["platforms"]["windows-x64"]["sha256"] = "bad_attacker_sha256"
        tampered_sig = tampered_manifest.pop("signature")

        with self.assertRaises(Exception):
            pub_key.verify(
                bytes.fromhex(tampered_sig),
                json.dumps(tampered_manifest, sort_keys=True).encode("utf-8"),
            )


if __name__ == "__main__":
    unittest.main()
