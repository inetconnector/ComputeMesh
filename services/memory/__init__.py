# SPDX-License-Identifier: Apache-2.0
"""ComputeMesh persistent memory package.

The legacy JSON user-memory API remains available for backward compatibility;
Agents Platform callers can opt into the structured scoped memory store.
"""

from .user_memory import (
    UserMemoryStore,
    get_user_memory_store,
    get_user_memory,
    update_user_memory,
    delete_user_memory,
)
from .structured_memory import (
    MemoryRecord,
    MemoryScope,
    MemoryType,
    Sensitivity,
    StructuredMemoryStore,
)

__all__ = [
    "UserMemoryStore",
    "get_user_memory_store",
    "get_user_memory",
    "update_user_memory",
    "delete_user_memory",
    "MemoryRecord",
    "MemoryScope",
    "MemoryType",
    "Sensitivity",
    "StructuredMemoryStore",
]
