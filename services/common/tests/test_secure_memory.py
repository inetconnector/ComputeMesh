from __future__ import annotations

import unittest
from unittest.mock import patch

from services.common import secure_memory
from services.common.secure_memory import (
    CryptographyUnavailableError,
    MemoryLockError,
    SecureMemoryBuffer,
    SecureMemoryError,
    secure_zero_memory,
)


class SecureMemoryTests(unittest.TestCase):
    def test_plaintext_view_is_mutable_backed_and_zeroized_on_exit(self) -> None:
        buf = SecureMemoryBuffer(b"top secret")
        backing = None
        with buf.open_plaintext() as view:
            self.assertIsInstance(view, memoryview)
            self.assertTrue(view.readonly)
            self.assertEqual(view.tobytes(), b"top secret")
            backing = view.obj
        self.assertIsInstance(backing, bytearray)
        self.assertEqual(bytes(backing), b"\x00" * len(backing))
        buf.zeroize()

    def test_buffer_is_single_use(self) -> None:
        buf = SecureMemoryBuffer(b"first")
        with self.assertRaises(SecureMemoryError):
            buf.write(b"second")
        buf.zeroize()

    def test_zeroization_overwrites_bytearray(self) -> None:
        value = bytearray(b"secret")
        secure_zero_memory(value)
        self.assertEqual(value, bytearray(len(value)))

    def test_missing_cryptography_fails_closed(self) -> None:
        with patch.object(secure_memory, "_HAS_CRYPTOGRAPHY", False):
            with self.assertRaises(CryptographyUnavailableError):
                SecureMemoryBuffer(b"secret")

    def test_required_memory_lock_fails_closed(self) -> None:
        with patch.object(secure_memory, "lock_memory_buffer", return_value=False):
            with self.assertRaises(MemoryLockError):
                SecureMemoryBuffer(b"secret", require_memory_lock=True)

    def test_plaintext_lock_failure_fails_before_yield(self) -> None:
        buf = SecureMemoryBuffer(b"secret")
        buf.require_memory_lock = True
        with patch.object(secure_memory, "lock_memory_buffer", return_value=False):
            with self.assertRaises(MemoryLockError):
                with buf.open_plaintext():
                    self.fail("plaintext must not be yielded without mandatory lock")
        buf.zeroize()


if __name__ == "__main__":
    unittest.main()
