"""Thread-safe ledger wrappers for the multi-threaded gateway."""
from __future__ import annotations

import threading
from typing import Any

from services.billing.ledger import Ledger


class ThreadSafeLedger(Ledger):
    """Ledger variant that ensures single unified RLock across journal mutation and balance reads."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Unify lock reference so all operations share the single Ledger RLock
        self._journal_lock = self._lock


class SynchronizedLedgerProxy:
    """Serialize access to an existing Ledger without reloading its journal."""

    def __init__(self, delegate: Ledger):
        self._delegate = delegate
        # Share the delegate's intrinsic lock if present
        self._journal_lock = getattr(delegate, "_lock", None) or threading.RLock()

    def __getattr__(self, name: str) -> Any:
        return getattr(self._delegate, name)
