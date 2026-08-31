"""Confidential Runtime Memory Hardening & Zeroization Adapter."""
from __future__ import annotations

from services.common.secure_memory import (
    SecureMemoryBuffer,
    lock_memory_buffer,
    secure_zero_memory,
    unlock_memory_buffer,
)

__all__ = [
    "SecureMemoryBuffer",
    "lock_memory_buffer",
    "unlock_memory_buffer",
    "secure_zero_memory",
]
