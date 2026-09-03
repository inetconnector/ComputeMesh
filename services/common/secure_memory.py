"""Protected in-memory buffers for confidential ComputeMesh execution.

The primitives in this module are defense in depth.  They reduce paging,
core-dump and plaintext-lifetime exposure inside a process, but they do not turn
an ordinary hostile host into a TEE.  `CONFIDENTIAL` execution must combine
these primitives with real hardware attestation and protected execution memory.
"""
from __future__ import annotations

from contextlib import contextmanager
import ctypes
import os
import platform
import secrets
from typing import Generator

try:
    from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

    _HAS_CRYPTOGRAPHY = True
except ImportError:
    _HAS_CRYPTOGRAPHY = False


class SecureMemoryError(RuntimeError):
    """Base error for protected-memory operations."""


class MemoryLockError(SecureMemoryError):
    """Raised when a mandatory page lock cannot be established."""


class CryptographyUnavailableError(SecureMemoryError):
    """Raised rather than falling back to a weaker ad-hoc cipher."""


_SYSTEM = platform.system()
_HAS_MLOCK = False
_libc = None

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


MutableBuffer = bytearray | ctypes.Array | memoryview


def memory_locking_available() -> bool:
    return _HAS_MLOCK


def _buffer_address_and_size(buffer: MutableBuffer) -> tuple[int, int]:
    if isinstance(buffer, ctypes.Array):
        return ctypes.addressof(buffer), ctypes.sizeof(buffer)
    if isinstance(buffer, bytearray):
        if not buffer:
            return 0, 0
        array = (ctypes.c_ubyte * len(buffer)).from_buffer(buffer)
        return ctypes.addressof(array), len(buffer)
    if isinstance(buffer, memoryview):
        if buffer.readonly or not buffer.contiguous:
            raise TypeError("memoryview must be writable and contiguous")
        view = buffer.cast("B")
        if view.nbytes == 0:
            return 0, 0
        array = (ctypes.c_ubyte * view.nbytes).from_buffer(view)
        return ctypes.addressof(array), view.nbytes
    raise TypeError("unsupported mutable buffer type")


def lock_memory_buffer(buffer: MutableBuffer) -> bool:
    """Lock mutable pages into RAM to prevent ordinary paging/swapping."""
    if not _HAS_MLOCK:
        return False
    try:
        ptr, size = _buffer_address_and_size(buffer)
        if size == 0:
            return True
        if _SYSTEM == "Windows":
            return bool(_VirtualLock(ptr, size))
        return _mlock(ptr, size) == 0
    except Exception:
        return False


def unlock_memory_buffer(buffer: MutableBuffer) -> bool:
    """Release a previously established page lock."""
    if not _HAS_MLOCK:
        return False
    try:
        ptr, size = _buffer_address_and_size(buffer)
        if size == 0:
            return True
        if _SYSTEM == "Windows":
            return bool(_VirtualUnlock(ptr, size))
        return _munlock(ptr, size) == 0
    except Exception:
        return False


def secure_zero_memory(target: MutableBuffer) -> None:
    """Overwrite a mutable buffer through a native memory operation."""
    ptr, size = _buffer_address_and_size(target)
    if size:
        ctypes.memset(ptr, 0, size)


def disable_process_core_dumps() -> bool:
    """Disable ordinary POSIX core dumps and Linux dumpability where supported.

    Windows crash-dump policy must be enforced by the production service/host
    configuration; this function therefore reports False on Windows rather than
    claiming protection it did not establish.
    """
    if os.name != "posix":
        return False
    try:
        import resource

        resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
    except (ImportError, OSError, ValueError):
        return False

    if _SYSTEM == "Linux" and _libc is not None and hasattr(_libc, "prctl"):
        try:
            # PR_SET_DUMPABLE = 4
            if _libc.prctl(4, 0, 0, 0, 0) != 0:
                return False
        except Exception:
            return False
    return True


class SecureMemoryBuffer:
    """Single-use AES-256-GCM envelope with bounded mutable plaintext exposure.

    `require_memory_lock=True` is intended for protected execution.  It makes
    inability to lock key/nonce/plaintext pages a hard error rather than silently
    continuing with a weaker memory posture.
    """

    def __init__(
        self,
        data: bytes | bytearray | memoryview | str | None = None,
        *,
        require_memory_lock: bool = False,
    ) -> None:
        if not _HAS_CRYPTOGRAPHY:
            raise CryptographyUnavailableError(
                "cryptography is required for protected AES-256-GCM memory envelopes"
            )
        self.require_memory_lock = require_memory_lock
        self._key = bytearray(secrets.token_bytes(32))
        self._nonce = bytearray(secrets.token_bytes(12))
        self._ciphertext = bytearray()
        self._tag = bytearray()
        self._is_zeroized = False
        self._key_locked = lock_memory_buffer(self._key)
        self._nonce_locked = lock_memory_buffer(self._nonce)
        if require_memory_lock and not (self._key_locked and self._nonce_locked):
            self.zeroize()
            raise MemoryLockError("mandatory key/nonce page locking could not be established")
        if data is not None:
            raw = data.encode("utf-8") if isinstance(data, str) else data
            self.write(raw)

    def write(self, plaintext: bytes | bytearray | memoryview) -> None:
        """Encrypt exactly one plaintext value into this request-scoped envelope."""
        if self._is_zeroized:
            raise SecureMemoryError("cannot write to a zeroized SecureMemoryBuffer")
        if self._ciphertext or self._tag:
            raise SecureMemoryError("SecureMemoryBuffer is single-use; create a new buffer")
        if not isinstance(plaintext, (bytes, bytearray, memoryview)):
            raise TypeError("plaintext must be bytes-like")

        cipher = Cipher(algorithms.AES(memoryview(self._key)), modes.GCM(memoryview(self._nonce)))
        encryptor = cipher.encryptor()
        ciphertext = encryptor.update(plaintext) + encryptor.finalize()
        self._ciphertext = bytearray(ciphertext)
        self._tag = bytearray(encryptor.tag)

    @contextmanager
    def open_plaintext(self) -> Generator[memoryview, None, None]:
        """Expose plaintext only as a mutable-backed read-only memoryview.

        The decrypted backing allocation is optionally page-locked before it is
        yielded and is zeroized before unlock on every exit path.  Returning a
        memoryview avoids the previous extra immutable `bytes` copy of protected
        plaintext.
        """
        if self._is_zeroized:
            raise SecureMemoryError("SecureMemoryBuffer has been zeroized")
        if not self._ciphertext:
            empty = bytearray()
            view = memoryview(empty).toreadonly()
            try:
                yield view
            finally:
                view.release()
            return

        cipher = Cipher(
            algorithms.AES(memoryview(self._key)),
            # cryptography's GCM API deliberately requires an immutable bytes tag.
            # This short-lived copy is authentication metadata, not protected plaintext.
            modes.GCM(memoryview(self._nonce), bytes(self._tag)),
        )
        decryptor = cipher.decryptor()
        # update_into requires room for up to block_size - 1 extra bytes.
        plaintext = bytearray(len(self._ciphertext) + 15)
        written = decryptor.update_into(self._ciphertext, plaintext)
        tail = decryptor.finalize()
        if tail:
            # GCM/AES should not leave plaintext in finalize after update_into.
            secure_zero_memory(plaintext)
            raise SecureMemoryError("unexpected final plaintext allocation")
        del plaintext[written:]

        locked = lock_memory_buffer(plaintext)
        if self.require_memory_lock and not locked:
            secure_zero_memory(plaintext)
            raise MemoryLockError("mandatory plaintext page locking could not be established")

        view = memoryview(plaintext).toreadonly()
        try:
            yield view
        finally:
            view.release()
            secure_zero_memory(plaintext)
            if locked:
                unlock_memory_buffer(plaintext)

    def zeroize(self) -> None:
        """Erase request-scoped keys, nonce, tag and ciphertext."""
        if self._is_zeroized:
            return
        for value in (self._ciphertext, self._tag, self._nonce, self._key):
            secure_zero_memory(value)
        if self._nonce_locked:
            unlock_memory_buffer(self._nonce)
        if self._key_locked:
            unlock_memory_buffer(self._key)
        self._is_zeroized = True

    def __enter__(self) -> "SecureMemoryBuffer":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.zeroize()

    def __del__(self) -> None:
        try:
            self.zeroize()
        except Exception:
            pass
