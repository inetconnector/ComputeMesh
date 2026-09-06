"""Unit tests for Cryptographic In-Memory Ephemeral RAM Hardening & Zeroization."""
from __future__ import annotations

import ctypes
from pathlib import Path
import sys
import unittest

REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from services.common.secure_memory import (
    SecureMemoryBuffer,
    lock_memory_buffer,
    secure_zero_memory,
    unlock_memory_buffer,
)


class TestSecureMemory(unittest.TestCase):
    def test_secure_memory_buffer_lifecycle(self) -> None:
        secret_payload = "super-sensitive-prompt-gdpr-confidential-compute"
        buf = SecureMemoryBuffer(secret_payload)

        # 1. Plaintext must NOT appear in raw ciphertext
        self.assertNotIn(secret_payload.encode("utf-8"), bytes(buf._ciphertext))
        self.assertEqual(len(buf._key), 32)
        self.assertEqual(len(buf._nonce), 12)

        # 2. Context manager temporarily exposes plaintext
        with buf.open_plaintext() as pt:
            self.assertEqual(bytes(pt).decode("utf-8"), secret_payload)

        # 3. Zeroization wipes all keys and ciphertexts
        buf.zeroize()
        self.assertTrue(all(b == 0 for b in buf._key))
        self.assertTrue(all(b == 0 for b in buf._nonce))
        self.assertTrue(all(b == 0 for b in buf._ciphertext))

        # 4. Access after zeroization raises RuntimeError
        with self.assertRaises(RuntimeError):
            with buf.open_plaintext():
                pass

    def test_secure_zero_memory_bytearray(self) -> None:
        arr = bytearray(b"sensitive_keys_1234567890")
        orig_len = len(arr)
        secure_zero_memory(arr)
        self.assertEqual(len(arr), orig_len)
        self.assertTrue(all(b == 0 for b in arr))

    def test_secure_zero_memory_ctypes_array(self) -> None:
        c_arr = (ctypes.c_char * 32)(*b"temporary_matrix_hidden_state_42")
        secure_zero_memory(c_arr)
        self.assertTrue(all(b == b"\x00" or b == 0 for b in c_arr))

    def test_memory_page_locking_safe(self) -> None:
        # Memory page locking should execute safely without crashing regardless of OS permissions
        c_arr = (ctypes.c_char * 1024)(*([0] * 1024))
        res_lock = lock_memory_buffer(c_arr)
        self.assertIsInstance(res_lock, bool)
        res_unlock = unlock_memory_buffer(c_arr)
        self.assertIsInstance(res_unlock, bool)


if __name__ == "__main__":
    unittest.main()
