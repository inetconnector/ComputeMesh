"""Real cryptographic negative tests for signed release artifact binding.

Uses an isolated temporary Git repository and an ephemeral TEST Ed25519 key.
Never loads, generates or alters the operator's production signing credentials.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat

from tools.release.verify_portal_bundle import REQUIRED, ReleaseGateError, verify_release
from tools.security import release_signer


class TestSignedPortalBundle(unittest.TestCase):
    TAG = "v1.2.189"

    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        self.root = Path(self.temp_dir.name)
        self.portal = self.root / "portal"
        self.downloads = self.portal / "downloads"
        self.downloads.mkdir(parents=True)
        (self.portal / "updates").mkdir()
        self.key = Ed25519PrivateKey.generate()
        self.public_key_hex = self.key.public_key().public_bytes(
            Encoding.Raw, PublicFormat.Raw
        ).hex()

        for platform, name in REQUIRED.items():
            # A dedicated test fixture; never a real installer or usable APK.
            (self.downloads / name).write_bytes(
                ("fixture:" + platform).encode("ascii")
            )
        apk = (self.downloads / "ComputeMesh-Android.apk").read_bytes()
        aab = (self.downloads / "ComputeMesh-Android.aab").read_bytes()
        self.metadata = {
            "production_signed": True,
            "package_name": "com.inetconnector.compumesh",
            "version_name": "1.2.189",
            "apk_sha256": hashlib.sha256(apk).hexdigest(),
            "apk_size": len(apk),
            "url": "https://mesh.inetconnector.com/downloads/ComputeMesh-Android.apk",
            "aab_sha256": hashlib.sha256(aab).hexdigest(),
            "aab_size": len(aab),
            "aab_url": "https://mesh.inetconnector.com/downloads/ComputeMesh-Android.aab",
        }
        self._write_metadata()
        download_links = (
            '<a href="/downloads/ComputeMesh-Setup-x64.exe">Windows</a>'
            '<a href="/downloads/install.sh">Linux</a>'
            '<a href="/downloads/ComputeMesh-Android.apk">Android</a>'
        )
        (self.portal / "downloads.html").write_text(download_links, encoding="utf-8")
        (self.downloads / "index.html").write_text(download_links, encoding="utf-8")
        self._sign_manifest()

        self._git("init", "-q")
        self._git("add", "portal/updates/version.json", "portal/downloads.html",
                  "portal/downloads/index.html")
        self._git("-c", "user.name=Release Fixture",
                  "-c", "user.email=fixture@example.invalid",
                  "commit", "-qm", "fixture")
        self._git("tag", self.TAG)

    def _git(self, *args: str) -> None:
        subprocess.run(
            ["git", "-C", str(self.root), *args], check=True,
            capture_output=True, timeout=15,
        )

    def _write_metadata(self) -> None:
        (self.downloads / "ComputeMesh-Android.json").write_text(
            json.dumps(self.metadata, sort_keys=True) + "\n", encoding="utf-8"
        )

    def _sign_manifest(self) -> None:
        # This overrides key discovery only, without weakening signature
        # verification. The signature itself is a real Ed25519 signature.
        with patch.object(
            release_signer, "get_or_create_keypair",
            return_value=(self.key, self.key.public_key()),
        ):
            release_signer.sign_manifest(
                "1.2.189", self.downloads,
                self.portal / "updates" / "version.json",
                base_url="https://mesh.inetconnector.com/downloads",
            )

    def _commit_and_retag(self) -> None:
        self._git("add", "portal/updates/version.json")
        self._git("-c", "user.name=Release Fixture",
                  "-c", "user.email=fixture@example.invalid",
                  "commit", "-qm", "new signed fixture")
        self._git("tag", "-f", self.TAG)

    def _verify(self) -> dict:
        # Test-only key pin; the production trusted key list is untouched.
        with patch.object(
            release_signer, "TRUSTED_RELEASE_PUBLIC_KEYS_HEX",
            (self.public_key_hex,),
        ):
            return verify_release(self.root, self.TAG, artifacts_dir=self.downloads)

    def test_fully_signed_inventory_is_accepted(self) -> None:
        receipt = self._verify()
        self.assertTrue(receipt["verified"])
        self.assertEqual(set(receipt["artifacts"]), set(REQUIRED))
        self.assertEqual(receipt["tag"], self.TAG)

    def test_modified_unsigned_android_metadata_is_rejected(self) -> None:
        self.metadata["apk_size"] += 1
        self._write_metadata()
        with self.assertRaisesRegex(
            ReleaseGateError, "SHA256 mismatch: ComputeMesh-Android.json"
        ):
            self._verify()

    def test_modified_android_apk_is_rejected(self) -> None:
        (self.downloads / "ComputeMesh-Android.apk").write_bytes(b"tampered-apk")
        with self.assertRaisesRegex(
            ReleaseGateError, "SHA256 mismatch: ComputeMesh-Android.apk"
        ):
            self._verify()

    def test_even_specially_signed_conflicting_metadata_is_rejected(self) -> None:
        self.metadata["apk_size"] += 1
        self._write_metadata()
        self._sign_manifest()
        self._commit_and_retag()
        with self.assertRaisesRegex(
            ReleaseGateError, "Android metadata does not match signed artifact"
        ):
            self._verify()

    def test_signed_manifest_without_android_entry_is_rejected(self) -> None:
        manifest_path = self.portal / "updates" / "version.json"
        data = json.loads(manifest_path.read_text(encoding="utf-8"))
        data["platforms"].pop("android-apk")
        data.pop("signature")
        data["signature"] = self.key.sign(
            json.dumps(data, sort_keys=True).encode("utf-8")
        ).hex()
        manifest_path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
        self._commit_and_retag()
        with self.assertRaisesRegex(ReleaseGateError, "missing signed platform: android-apk"):
            self._verify()


if __name__ == "__main__":
    unittest.main()
