# SPDX-License-Identifier: Apache-2.0
"""ComputeMesh persistent memory package.

The legacy JSON user-memory API remains available for backward compatibility;
Agents Platform callers can opt into the structured scoped memory store.
"""

from .structured_memory import (
    MemoryRecord,
    MemoryScope,
    MemoryType,
    Sensitivity,
    StructuredMemoryStore,
)
from .user_memory import (
    UserMemoryStore,
    delete_user_memory,
    get_user_memory,
    get_user_memory_store,
    update_user_memory,
)

__all__ = [
    "MemoryRecord",
    "MemoryScope",
    "MemoryType",
    "Sensitivity",
    "StructuredMemoryStore",
    "UserMemoryStore",
    "delete_user_memory",
    "get_user_memory",
    "get_user_memory_store",
    "update_user_memory",
]
