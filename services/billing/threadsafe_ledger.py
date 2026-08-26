"""Thread-safe ledger wrappers for the multi-threaded gateway."""
from __future__ import annotations

import threading
from typing import Any

from services.billing.ledger import Ledger


class ThreadSafeLedger(Ledger):
    """Ledger variant that serializes journal mutation and balance reads."""

    def __init__(self, *args, **kwargs):
        self._journal_lock = threading.RLock()
        super().__init__(*args, **kwargs)

    def deposit_customer_credits(self, **kwargs):
        with self._journal_lock:
            return super().deposit_customer_credits(**kwargs)

    def record_job_execution(self, **kwargs):
        with self._journal_lock:
            return super().record_job_execution(**kwargs)

    def create_operator_treasury_payout(self, *args, **kwargs):
        with self._journal_lock:
            return super().create_operator_treasury_payout(*args, **kwargs)

    def create_provider_payout(self, **kwargs):
        with self._journal_lock:
            return super().create_provider_payout(**kwargs)

    def get_balance(self, account_id: str) -> int:
        with self._journal_lock:
            return super().get_balance(account_id)

    def get_platform_revenue_micro_units(self) -> int:
        with self._journal_lock:
            return super().get_platform_revenue_micro_units()

    def get_platform_revenue_usd(self) -> float:
        with self._journal_lock:
            return super().get_platform_revenue_usd()

    def reconcile(self):
        with self._journal_lock:
            return super().reconcile()


class SynchronizedLedgerProxy:
    """Serialize access to an existing Ledger without reloading its journal."""

    def __init__(self, delegate: Ledger):
        self._delegate = delegate
        self._journal_lock = threading.RLock()

    def __getattr__(self, name: str) -> Any:
        return getattr(self._delegate, name)

    def deposit_customer_credits(self, **kwargs):
        with self._journal_lock:
            return self._delegate.deposit_customer_credits(**kwargs)

    def record_job_execution(self, **kwargs):
        with self._journal_lock:
            return self._delegate.record_job_execution(**kwargs)

    def create_operator_treasury_payout(self, *args, **kwargs):
        with self._journal_lock:
            return self._delegate.create_operator_treasury_payout(*args, **kwargs)

    def create_provider_payout(self, **kwargs):
        with self._journal_lock:
            return self._delegate.create_provider_payout(**kwargs)

    def get_balance(self, account_id: str) -> int:
        with self._journal_lock:
            return self._delegate.get_balance(account_id)

    def get_platform_revenue_micro_units(self) -> int:
        with self._journal_lock:
            return self._delegate.get_platform_revenue_micro_units()

    def get_platform_revenue_usd(self) -> float:
        with self._journal_lock:
            return self._delegate.get_platform_revenue_usd()

    def reconcile(self):
        with self._journal_lock:
            return self._delegate.reconcile()
