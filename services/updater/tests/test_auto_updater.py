"""Unit tests for ComputeMesh Cryptographic Auto-Updater."""
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

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
        # Monotonic progression requirement: 1.2.189 > 1.2.188 > 1.2.187 > 1.2.186 > 1.2.185
        v185 = AutoUpdater._parse_version("1.2.185")
        v186 = AutoUpdater._parse_version("1.2.186")
        v187 = AutoUpdater._parse_version("1.2.187")
        v188 = AutoUpdater._parse_version("1.2.188")
        v189 = AutoUpdater._parse_version("1.2.189")
        self.assertTrue(v186 > v185)
        self.assertTrue(v187 > v186)
        self.assertTrue(v188 > v187)
        self.assertTrue(v189 > v188)
        self.assertTrue(v189 > v185)
        self.assertFalse(v185 > v186)

    def test_nodeos_platform_detection(self) -> None:
        with patch("platform.system", return_value="Linux"):
            with patch.object(Path, "exists", side_effect=lambda: True):
                self.assertEqual(self.updater._get_platform_key(), "nodeos-img")
        with patch("platform.system", return_value="Linux"):
            with patch.object(Path, "exists", side_effect=lambda: False):
                self.assertEqual(self.updater._get_platform_key(), "linux-x64")

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

    def test_linux_update_targets_require_absolute_paths(self) -> None:
        with patch.dict(
            os.environ,
            {"COMPUTEMESH_LINUX_UPDATE_TARGETS": f"/srv/one{os.pathsep}/srv/one{os.pathsep}/srv/two"},
            clear=False,
        ):
            self.assertEqual(
                AutoUpdater._linux_update_targets(),
                [Path("/srv/one"), Path("/srv/two")],
            )

        with patch.dict(os.environ, {"COMPUTEMESH_LINUX_UPDATE_TARGETS": "relative/path"}, clear=False):
            with self.assertRaisesRegex(ValueError, "absolute paths"):
                AutoUpdater._linux_update_targets()

    def test_linux_update_services_are_validated_and_deduplicated(self) -> None:
        with patch.dict(
            os.environ,
            {"COMPUTEMESH_LINUX_UPDATE_SERVICES": "computemesh-gateway.service computemesh-node.service computemesh-gateway.service"},
            clear=False,
        ):
            self.assertEqual(
                AutoUpdater._linux_update_services(),
                ["computemesh-gateway.service", "computemesh-node.service"],
            )

        with patch.dict(os.environ, {"COMPUTEMESH_LINUX_UPDATE_SERVICES": "sh -c evil"}, clear=False):
            with self.assertRaisesRegex(ValueError, "invalid systemd unit"):
                AutoUpdater._linux_update_services()

    def test_linux_update_uses_configured_targets_and_units(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            target = Path(temp_dir) / "target"
            target.mkdir()
            package = Path(temp_dir) / "update.tar.gz"
            package.touch()
            with patch.object(AutoUpdater, "_linux_update_targets", return_value=[target]), patch.object(
                AutoUpdater,
                "_linux_update_services",
                return_value=["computemesh-gateway.service", "computemesh-node.service"],
            ), patch("shutil.unpack_archive") as unpack, patch("subprocess.Popen") as popen:
                self.updater.apply_linux_update(package)

            unpack.assert_called_once_with(str(package), str(target))
            popen.assert_called_once_with(
                ["systemctl", "restart", "computemesh-gateway.service", "computemesh-node.service"],
                stdout=unittest.mock.ANY,
                stderr=unittest.mock.ANY,
            )


if __name__ == "__main__":
    unittest.main()
