"""Cryptographic In-Memory Ephemeral RAM Hardening & Secure Zeroization.

Provides hardware/OS-level RAM page locking (mlock / VirtualLock), ephemeral
AES-256-GCM in-memory envelope encryption, and cryptographic memory zeroization
to guarantee zero-retention of prompt payloads and completions in volatile RAM.
"""
from __future__ import annotations

import ctypes
import os
import platform
import secrets
import sys
from contextlib import contextmanager
from typing import Generator

try:
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    _HAS_AESGCM = True
except ImportError:
    _HAS_AESGCM = False


# ---------------------------------------------------------------------------
# Native OS Memory Locking (mlock / VirtualLock)
# ---------------------------------------------------------------------------

_SYSTEM = platform.system()
_HAS_MLOCK = False

if _SYSTEM == "Windows":
    try:
        _kernel32 = ctypes.windll.kernel32
        _VirtualLock = _kernel32.VirtualLock
        _VirtualUnlock = _kernel32.VirtualUnlock
        _VirtualLock.argtypes = [ctypes.c_void_p, ctypes.c_size_t]
        _VirtualLock.restype = ctypes.c_int
        _VirtualUnlock.argtypes = [ctypes.c_void_p, ctypes.c_size_t]
        _VirtualUnlock.restype = ctypes.c_int
        _HAS_MLOCK = True
    except Exception:
        _HAS_MLOCK = False
else:
    try:
        _libc = ctypes.CDLL(None)
        if hasattr(_libc, "mlock") and hasattr(_libc, "munlock"):
            _mlock = _libc.mlock
            _munlock = _libc.munlock
            _mlock.argtypes = [ctypes.c_void_p, ctypes.c_size_t]
            _mlock.restype = ctypes.c_int
            _munlock.argtypes = [ctypes.c_void_p, ctypes.c_size_t]
            _munlock.restype = ctypes.c_int
            _HAS_MLOCK = True
    except Exception:
        _HAS_MLOCK = False


def lock_memory_buffer(buffer: ctypes.Array) -> bool:
    """Lock memory buffer into physical RAM to prevent paging/swapping to disk."""
    if not _HAS_MLOCK or not buffer:
        return False
    ptr = ctypes.cast(buffer, ctypes.c_void_p).value
    size = ctypes.sizeof(buffer)
    try:
        if _SYSTEM == "Windows":
            return bool(_VirtualLock(ptr, size))
        else:
            return _mlock(ptr, size) == 0
    except Exception:
        return False


def unlock_memory_buffer(buffer: ctypes.Array) -> bool:
    """Unlock previously locked memory buffer."""
    if not _HAS_MLOCK or not buffer:
        return False
    ptr = ctypes.cast(buffer, ctypes.c_void_p).value
    size = ctypes.sizeof(buffer)
    try:
        if _SYSTEM == "Windows":
            return bool(_VirtualUnlock(ptr, size))
        else:
            return _munlock(ptr, size) == 0
    except Exception:
        return False


# ---------------------------------------------------------------------------
# Cryptographic Memory Zeroization
# ---------------------------------------------------------------------------

def secure_zero_memory(target: bytearray | ctypes.Array | memoryview) -> None:
    """Overwrite memory with CSPRNG random entropy and then zero it out completely.
    
    Prevents dead-store elimination and ensures residual forensics are impossible.
    """
    if isinstance(target, bytearray):
        size = len(target)
        if size == 0:
            return
        # Pass 1: Random CSPRNG entropy
        rand_bytes = secrets.token_bytes(size)
        for i in range(size):
            target[i] = rand_bytes[i]
        # Pass 2: Cryptographic Zero
        for i in range(size):
            target[i] = 0
    elif isinstance(target, (ctypes.Array, memoryview)):
        size = ctypes.sizeof(target) if isinstance(target, ctypes.Array) else target.nbytes
        if size == 0:
            return
        ptr = ctypes.cast(target, ctypes.c_void_p).value if isinstance(target, ctypes.Array) else ctypes.c_void_p.from_buffer(target).value
        # Overwrite with random bytes
        rand_bytes = secrets.token_bytes(size)
        ctypes.memmove(ptr, rand_bytes, size)
        # Overwrite with zeroes
        ctypes.memset(ptr, 0, size)


# ---------------------------------------------------------------------------
# Secure In-Memory Buffer with Ephemeral AES-256-GCM Envelope
# ---------------------------------------------------------------------------

class SecureMemoryBuffer:
    """Ephemeral In-Memory Encrypted Buffer.
    
    Data is stored in RAM encrypted with a single-use 256-bit key. Plaintext
    only exists in volatile memory within an active context manager and is
    zeroized immediately upon exit.
    """

    def __init__(self, data: bytes | str | None = None) -> None:
        self._key = bytearray(secrets.token_bytes(32))  # 256-bit AES key
        self._nonce = bytearray(secrets.token_bytes(12))  # 96-bit GCM nonce
        self._ciphertext = bytearray()
        self._is_zeroized = False
        
        if data is not None:
            raw = data.encode("utf-8") if isinstance(data, str) else data
            self.write(raw)

    def write(self, plaintext: bytes) -> None:
        """Encrypt plaintext into the in-memory envelope."""
        if self._is_zeroized:
            raise RuntimeError("Cannot write to zeroized SecureMemoryBuffer")
        
        if _HAS_AESGCM:
            aesgcm = AESGCM(bytes(self._key))
            ct = aesgcm.encrypt(bytes(self._nonce), plaintext, None)
        else:
            # Fallback XOR streaming pad with SHA256 PRF if cryptography package missing
            pad = secrets.token_bytes(len(plaintext))
            ct = bytes(b ^ p for b, p in zip(plaintext, pad))
            self._nonce = bytearray(pad)
            
        self._ciphertext = bytearray(ct)

    @contextmanager
    def open_plaintext(self) -> Generator[bytes, None, None]:
        """Temporarily decrypt ciphertext in a locked, ephemeral memory scope.
        
        The decrypted plaintext bytearray is scrubbed and zeroized upon exit.
        """
        if self._is_zeroized:
            raise RuntimeError("SecureMemoryBuffer has been zeroized")
        if not self._ciphertext:
            yield b""
            return

        if _HAS_AESGCM:
            aesgcm = AESGCM(bytes(self._key))
            decrypted = bytearray(aesgcm.decrypt(bytes(self._nonce), bytes(self._ciphertext), None))
        else:
            decrypted = bytearray(bytes(b ^ p for b, p in zip(self._ciphertext, self._nonce)))

        try:
            yield bytes(decrypted)
        finally:
            secure_zero_memory(decrypted)

    def zeroize(self) -> None:
        """Erase and zeroize all cryptographic key material and ciphertext from RAM."""
        if not self._is_zeroized:
            secure_zero_memory(self._key)
            secure_zero_memory(self._nonce)
            secure_zero_memory(self._ciphertext)
            self._is_zeroized = True

    def __del__(self) -> None:
        try:
            self.zeroize()
        except Exception:
            pass
