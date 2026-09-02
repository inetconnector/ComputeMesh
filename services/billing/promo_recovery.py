"""Reconcile an existing durable promo claim with its deterministic ledger event."""
from __future__ import annotations

from services.billing.ledger import DuplicateEventError
from services.billing.owner_accounts import OwnerAccountStore
from services.billing.owner_credits import OwnerCreditLedger
from services.billing.signed_promo_grants import PromoGrantApplyResult


def reconcile_existing_promo_claim(
    *,
    owner_store: OwnerAccountStore,
    ledger: OwnerCreditLedger,
    owner_id: str,
    claim_class: str,
) -> PromoGrantApplyResult | None:
    """Ensure one previously authorized durable claim is reflected in the ledger."""
    claim = owner_store.promo_claim_for_owner(owner_id, claim_class)
    if claim is None:
        return None

    ledger_status = "credited_recovery"
    try:
        ledger.grant_owner_promo_credits(
            owner_id=claim.owner_id,
            amount_micro_units=claim.amount_micro_units,
            grant_reference=claim.claim_id,
            policy_version=claim.policy_version,
        )
    except DuplicateEventError:
        ledger_status = "already_credited"

    return PromoGrantApplyResult(
        owner_id=claim.owner_id,
        claim_id=claim.claim_id,
        claim_class=claim.claim_class,
        amount_micro_units=claim.amount_micro_units,
        policy_version=claim.policy_version,
        ledger_status=ledger_status,
        claim=claim,
    )
