"""Unified owner ledger with payout and durable confidential-job escrow."""
from __future__ import annotations

from services.billing.confidential_escrow import ConfidentialEscrowOwnerCreditLedger
from services.billing.owner_settlement import PayoutCapableOwnerLedger


class PayoutCapableConfidentialOwnerLedger(
    PayoutCapableOwnerLedger,
    ConfidentialEscrowOwnerCreditLedger,
):
    """Production migration target combining owner payout and confidential escrow.

    Both parents share ``GatewayOwnerCreditLedger`` as their common base. Neither
    introduces a competing constructor, so one append-only journal and one RLock
    back all owner buckets, withdrawals and confidential reservations.
    """

    pass
