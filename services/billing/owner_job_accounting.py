"""Owner-aware settlement math for marketplace, self-compute and mixed jobs.

The token/model price remains the gross reference value of a job. A customer's
actual debit depends on who supplied the compute:

- foreign-provider share: customer pays the full gross share; the configured
  marketplace/operator fee is retained and the rest becomes provider earned credit;
- own-provider share: the owner is not paid and re-credited for their own work;
  only the configured self-compute infrastructure fee is debited;
- mixed jobs apply both rules proportionally.

This module is intentionally pure settlement math plus an adapter to the unified
owner credit ledger. Provider ownership resolution happens before this boundary and
must fail closed when ambiguous.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from services.billing.ledger import BillingError
from services.billing.owner_credits import (
    OWNER_EARNED,
    CreditDestination,
    OwnerCreditHold,
    OwnerCreditLedger,
    OwnerSpendResult,
    owner_bucket_account,
)


@dataclass(frozen=True)
class ProviderOwnerShare:
    provider_node_id: str
    owner_id: str
    ratio: float


@dataclass(frozen=True)
class ProviderSettlementShare:
    provider_node_id: str
    owner_id: str
    gross_micro_units: int
    operator_fee_micro_units: int
    provider_earned_micro_units: int
    is_self_compute: bool


@dataclass(frozen=True)
class OwnerJobQuote:
    customer_owner_id: str
    gross_reference_micro_units: int
    customer_charge_micro_units: int
    operator_fee_micro_units: int
    self_compute_gross_micro_units: int
    foreign_compute_gross_micro_units: int
    provider_earned_by_owner: tuple[tuple[str, int], ...]
    provider_shares: tuple[ProviderSettlementShare, ...]

    @property
    def is_pure_self_compute(self) -> bool:
        return self.self_compute_gross_micro_units == self.gross_reference_micro_units

    @property
    def is_pure_marketplace(self) -> bool:
        return self.foreign_compute_gross_micro_units == self.gross_reference_micro_units


def _clean_identifier(value: str, *, field: str) -> str:
    text = str(value or "").strip()
    if not text:
        raise BillingError(f"{field} is required")
    if len(text) > 256:
        raise BillingError(f"{field} is too long")
    return text


def _validate_bps(value: int, *, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or not 0 <= value <= 10_000:
        raise BillingError(f"{field} must be an integer from 0 to 10000 basis points")
    return value


def _fee_for_share(amount: int, fee_bps: int) -> int:
    if amount <= 0 or fee_bps <= 0:
        return 0
    if fee_bps >= 10_000:
        return amount
    # A configured non-zero fee must not disappear solely because integer
    # micro-unit rounding produced zero on a tiny settlement share.
    return min(amount, max(1, (amount * fee_bps) // 10_000))


def _allocate_gross(
    gross_micro_units: int,
    shares: tuple[ProviderOwnerShare, ...],
) -> tuple[int, ...]:
    if gross_micro_units <= 0:
        raise BillingError("gross job charge must be positive")
    if not shares:
        raise BillingError("at least one provider share is required")

    total_ratio = 0.0
    for share in shares:
        _clean_identifier(share.provider_node_id, field="provider_node_id")
        _clean_identifier(share.owner_id, field="provider owner_id")
        if isinstance(share.ratio, bool) or not isinstance(share.ratio, (int, float)):
            raise BillingError("provider share ratio must be numeric")
        if share.ratio <= 0:
            raise BillingError("provider share ratio must be positive")
        total_ratio += float(share.ratio)
    if total_ratio <= 0:
        raise BillingError("provider share total must be positive")

    remaining = gross_micro_units
    allocations: list[int] = []
    for index, share in enumerate(shares):
        if index == len(shares) - 1:
            amount = remaining
        else:
            amount = int(gross_micro_units * float(share.ratio) / total_ratio)
            amount = min(amount, remaining)
        allocations.append(amount)
        remaining -= amount
    if remaining != 0 or sum(allocations) != gross_micro_units:
        raise BillingError("provider gross allocation did not reconcile")
    return tuple(allocations)


def quote_owner_job(
    *,
    customer_owner_id: str,
    gross_reference_micro_units: int,
    provider_shares: Iterable[ProviderOwnerShare],
    marketplace_fee_bps: int = 2500,
    self_compute_fee_bps: int = 1000,
) -> OwnerJobQuote:
    """Calculate the exact customer debit and provider/operator destinations."""
    customer_owner = _clean_identifier(customer_owner_id, field="customer_owner_id")
    marketplace_fee = _validate_bps(marketplace_fee_bps, field="marketplace_fee_bps")
    self_fee = _validate_bps(self_compute_fee_bps, field="self_compute_fee_bps")
    shares = tuple(provider_shares)
    gross_allocations = _allocate_gross(gross_reference_micro_units, shares)

    customer_charge = 0
    operator_fee_total = 0
    self_gross = 0
    foreign_gross = 0
    earned_by_owner: dict[str, int] = {}
    settlement_shares: list[ProviderSettlementShare] = []

    for share, gross in zip(shares, gross_allocations, strict=True):
        is_self = share.owner_id == customer_owner
        if is_self:
            fee = _fee_for_share(gross, self_fee)
            earned = 0
            customer_charge += fee
            operator_fee_total += fee
            self_gross += gross
        else:
            fee = _fee_for_share(gross, marketplace_fee)
            earned = gross - fee
            customer_charge += gross
            operator_fee_total += fee
            foreign_gross += gross
            if earned:
                earned_by_owner[share.owner_id] = earned_by_owner.get(share.owner_id, 0) + earned

        settlement_shares.append(
            ProviderSettlementShare(
                provider_node_id=share.provider_node_id,
                owner_id=share.owner_id,
                gross_micro_units=gross,
                operator_fee_micro_units=fee,
                provider_earned_micro_units=earned,
                is_self_compute=is_self,
            )
        )

    destinations_total = operator_fee_total + sum(earned_by_owner.values())
    if destinations_total != customer_charge:
        raise BillingError(
            "owner job quote is unbalanced: customer debit does not match fee + provider earnings"
        )

    return OwnerJobQuote(
        customer_owner_id=customer_owner,
        gross_reference_micro_units=gross_reference_micro_units,
        customer_charge_micro_units=customer_charge,
        operator_fee_micro_units=operator_fee_total,
        self_compute_gross_micro_units=self_gross,
        foreign_compute_gross_micro_units=foreign_gross,
        provider_earned_by_owner=tuple(sorted(earned_by_owner.items())),
        provider_shares=tuple(settlement_shares),
    )


def quote_destinations(quote: OwnerJobQuote) -> tuple[CreditDestination, ...]:
    """Convert a quote into balanced ledger credit destinations."""
    destinations: list[CreditDestination] = []
    if quote.operator_fee_micro_units:
        destinations.append(
            CreditDestination(
                account_id="revenue:network_fee",
                account_type="revenue:network_fee",
                amount_micro_units=quote.operator_fee_micro_units,
            )
        )
    for owner_id, amount in quote.provider_earned_by_owner:
        if amount:
            destinations.append(
                CreditDestination(
                    account_id=owner_bucket_account(owner_id, "earned"),
                    account_type=OWNER_EARNED,
                    amount_micro_units=amount,
                )
            )
    if quote.customer_charge_micro_units and not destinations:
        raise BillingError("billable owner job has no ledger destinations")
    return tuple(destinations)


def capture_owner_job_hold(
    ledger: OwnerCreditLedger,
    *,
    hold: OwnerCreditHold,
    quote: OwnerJobQuote,
    job_id: str,
) -> OwnerSpendResult | None:
    """Atomically capture an inference hold into fee/provider owner destinations.

    ``None`` is possible only for a zero-fee pure self-compute policy. Production
    policy is expected to configure a non-zero self-compute fee, but keeping this
    edge explicit makes the accounting behavior deterministic for tests/research.
    """
    if hold.owner_id != quote.customer_owner_id:
        raise BillingError("owner job quote does not belong to the hold owner")
    if quote.customer_charge_micro_units > hold.amount_micro_units:
        raise BillingError("owner job customer charge exceeds the reserved hold")
    job_reference = _clean_identifier(job_id, field="job_id")
    if quote.customer_charge_micro_units == 0:
        ledger.release_owner_hold(hold.hold_id)
        return None
    return ledger.capture_owner_hold(
        hold_id=hold.hold_id,
        actual_amount_micro_units=quote.customer_charge_micro_units,
        destinations=quote_destinations(quote),
        spend_reference=f"job:{job_reference}",
        description=(
            f"Owner-aware inference settlement {job_reference}; "
            f"gross={quote.gross_reference_micro_units}, "
            f"self={quote.self_compute_gross_micro_units}, "
            f"foreign={quote.foreign_compute_gross_micro_units}"
        ),
    )
