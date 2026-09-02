"""Gateway compatibility adapter for the unified owner credit ledger.

Some mature gateway/payment code still calls the legacy ``deposit_customer_credits``
and ``get_balance(account_id)`` surface. During the migration this adapter routes
normal durable customer/owner deposits into ``purchased`` owner credits while
keeping ephemeral teaser accounts on the legacy demo balance path.

New code should prefer the explicit owner APIs on :class:`OwnerCreditLedger`.
"""
from __future__ import annotations

from services.billing.ledger import Ledger, Transaction
from services.billing.owner_credits import OwnerCreditLedger, owner_bucket_account


class GatewayOwnerCreditLedger(OwnerCreditLedger):
    """Transitional adapter used only when unified owner mode is explicitly enabled."""

    @staticmethod
    def _is_demo_account(account_id: str) -> bool:
        return str(account_id or "").startswith("teaser_")

    @staticmethod
    def _is_internal_account(account_id: str) -> bool:
        value = str(account_id or "")
        return (
            value.startswith("owner:")
            or value.startswith("provider:")
            or value.startswith("revenue:")
            or value.startswith("expense:")
            or value.startswith("gateway:")
            or value.startswith("asset:")
            or value.startswith("liability:")
        )

    def deposit_customer_credits(
        self,
        *,
        customer_account_id: str,
        amount_micro_units: int,
        payment_reference: str,
    ) -> Transaction:
        if self._is_demo_account(customer_account_id):
            return Ledger.deposit_customer_credits(
                self,
                customer_account_id=customer_account_id,
                amount_micro_units=amount_micro_units,
                payment_reference=payment_reference,
            )
        return self.deposit_owner_purchased_credits(
            owner_id=customer_account_id,
            amount_micro_units=amount_micro_units,
            payment_reference=payment_reference,
        )

    def get_balance(self, account_id: str) -> int:
        """Return legacy/internal balance or aggregate owner spendable balance.

        This keeps Stripe reconciliation and older read-only balance callers working
        while new endpoints expose the individual earned/purchased/promo buckets.
        """
        if self._is_demo_account(account_id) or self._is_internal_account(account_id):
            return Ledger.get_balance(self, account_id)

        owner_accounts = (
            owner_bucket_account(account_id, "earned"),
            owner_bucket_account(account_id, "purchased"),
            owner_bucket_account(account_id, "promo"),
        )
        with self._lock:
            if any(item in self._balances for item in owner_accounts):
                return sum(max(0, Ledger.get_balance(self, item)) for item in owner_accounts)
        return Ledger.get_balance(self, account_id)
