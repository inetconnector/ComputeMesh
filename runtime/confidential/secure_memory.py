"""Confidential runtime memory-hardening adapter."""
from __future__ import annotations

from services.common.secure_memory import (
    CryptographyUnavailableError,
    MemoryLockError,
    SecureMemoryBuffer,
    SecureMemoryError,
    disable_process_core_dumps,
    lock_memory_buffer,
    memory_locking_available,
    secure_zero_memory,
    unlock_memory_buffer,
)

__all__ = [
    "CryptographyUnavailableError",
    "MemoryLockError",
    "SecureMemoryBuffer",
    "SecureMemoryError",
    "disable_process_core_dumps",
    "lock_memory_buffer",
    "memory_locking_available",
    "secure_zero_memory",
    "unlock_memory_buffer",
]
