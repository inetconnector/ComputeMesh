import os
from pathlib import Path
import platform
import stat
import tempfile
import unittest

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from tools.security.node_key_storage import (
    DPAPI_ENVELOPE_PREFIX,
    KeyStorageError,
    _HAS_DPAPI,
    dpapi_protect,
    dpapi_unprotect,
    load_node_private_key,
    save_node_private_key,
    shred_node_key,
)


class TestNodeKeyStorage(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name)
        self.key = Ed25519PrivateKey.generate()

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_save_and_load_plain_pem(self) -> None:
        key_path = self.root / "node.pem"
        save_node_private_key(self.key, key_path, protect_os=False)

        self.assertTrue(key_path.is_file())
        content = key_path.read_bytes()
        self.assertTrue(content.startswith(b"-----BEGIN PRIVATE KEY-----"))

        loaded = load_node_private_key(key_path)
        self.assertIsInstance(loaded, Ed25519PrivateKey)

        # Verify cryptographic identity: signatures match
        data = b"benchmark-payload-test-123"
        sig1 = self.key.sign(data)
        sig2 = loaded.sign(data)
        self.assertEqual(sig1, sig2)

    def test_save_and_load_os_protected(self) -> None:
        key_path = self.root / "node_protected.pem"
        save_node_private_key(self.key, key_path, protect_os=True)
        self.assertTrue(key_path.is_file())

        if platform.system().lower() == "windows" and _HAS_DPAPI:
            content = key_path.read_text(encoding="ascii")
            self.assertTrue(content.startswith(DPAPI_ENVELOPE_PREFIX))

        loaded = load_node_private_key(key_path)
        self.assertIsInstance(loaded, Ed25519PrivateKey)

        data = b"challenge-auth-token-456"
        sig = loaded.sign(data)
        # Verify with public key
        self.key.public_key().verify(sig, data)

    def test_load_raw_32_bytes(self) -> None:
        raw = self.key.private_bytes(
            encoding=serialization.Encoding.Raw,
            format=serialization.PrivateFormat.Raw,
            encryption_algorithm=serialization.NoEncryption(),
        )
        key_path = self.root / "raw.key"
        key_path.write_bytes(raw)

        loaded = load_node_private_key(key_path)
        self.assertIsInstance(loaded, Ed25519PrivateKey)
        self.assertEqual(loaded.sign(b"test"), self.key.sign(b"test"))

    def test_load_base64_32_bytes(self) -> None:
        import base64
        raw = self.key.private_bytes(
            encoding=serialization.Encoding.Raw,
            format=serialization.PrivateFormat.Raw,
            encryption_algorithm=serialization.NoEncryption(),
        )
        b64 = base64.b64encode(raw)
        key_path = self.root / "b64.key"
        key_path.write_bytes(b64)

        loaded = load_node_private_key(key_path)
        self.assertIsInstance(loaded, Ed25519PrivateKey)
        self.assertEqual(loaded.sign(b"test"), self.key.sign(b"test"))


    def test_dpapi_roundtrip_if_windows(self) -> None:
        if platform.system().lower() != "windows" or not _HAS_DPAPI:
            self.skipTest("DPAPI only supported on Windows")

        secret = b"my-super-secret-node-key-material"
        protected = dpapi_protect(secret, "Test Protection")
        self.assertNotEqual(secret, protected)

        unprotected = dpapi_unprotect(protected)
        self.assertEqual(secret, unprotected)

    def test_load_non_existent_key_raises_error(self) -> None:
        with self.assertRaises(KeyStorageError):
            load_node_private_key(self.root / "missing.pem")

    def test_load_empty_key_raises_error(self) -> None:
        empty_path = self.root / "empty.pem"
        empty_path.write_bytes(b"")
        with self.assertRaises(KeyStorageError):
            load_node_private_key(empty_path)

    def test_load_invalid_content_raises_error(self) -> None:
        invalid_path = self.root / "invalid.pem"
        invalid_path.write_bytes(b"not-a-pem-or-key")
        with self.assertRaises(KeyStorageError):
            load_node_private_key(invalid_path)

    @unittest.skipUnless(os.name == "posix", "POSIX permission hardening only")
    def test_load_rejects_group_or_world_readable_key(self) -> None:
        key_path = self.root / "too-open.pem"
        save_node_private_key(self.key, key_path, protect_os=False)
        os.chmod(key_path, 0o644)
        with self.assertRaises(KeyStorageError):
            load_node_private_key(key_path)

    @unittest.skipUnless(os.name == "posix", "POSIX permission hardening only")
    def test_load_rejects_group_or_world_accessible_directory(self) -> None:
        key_dir = self.root / "too-open-dir"
        key_dir.mkdir()
        key_path = key_dir / "node.pem"
        save_node_private_key(self.key, key_path, protect_os=False)
        os.chmod(key_dir, 0o755)
        with self.assertRaises(KeyStorageError):
            load_node_private_key(key_path)

    def test_save_rejects_existing_symlink(self) -> None:
        if not hasattr(os, "symlink"):
            self.skipTest("symlinks unavailable")
        target = self.root / "target.pem"
        target.write_bytes(b"must-not-be-overwritten")
        link = self.root / "node.pem"
        try:
            link.symlink_to(target)
        except (OSError, NotImplementedError) as exc:
            self.skipTest(f"symlink creation unavailable: {exc}")
        with self.assertRaises(KeyStorageError):
            save_node_private_key(self.key, link, protect_os=False)
        self.assertEqual(target.read_bytes(), b"must-not-be-overwritten")

    def test_shred_node_key(self) -> None:
        key_path = self.root / "shred_me.pem"
        save_node_private_key(self.key, key_path, protect_os=False)
        self.assertTrue(key_path.is_file())

        result = shred_node_key(key_path)
        self.assertTrue(result)
        self.assertFalse(key_path.exists())

        # Shredding again returns False (not found)
        self.assertFalse(shred_node_key(key_path))


if __name__ == "__main__":
    unittest.main()
