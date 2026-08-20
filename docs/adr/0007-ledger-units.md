# ADR 0007: Ledger Precision and Monetary Units

- **Status:** Proposed
- **Date:** 2026-08-20

## Context

Per-token/per-millisecond provider economics may require precision below a currency cent. Floating-point accounting is unacceptable.

## Proposed decision

- customer-visible money uses integer currency minor units;
- internal metering uses integer physical units (for example accepted device-milliseconds and bytes);
- an explicit deterministic pricing function converts metering to high-resolution internal monetary units;
- settlement rounding occurs at a defined aggregation boundary;
- ledger is append-only double-entry.

The exact high-resolution monetary unit is still to be selected.

## Verification

Property tests must prove:

- debits equal credits;
- same inputs produce same rounding;
- duplicates have one effect;
- refund cannot exceed attributable charge;
- aggregation order does not change final settled amount beyond the defined rounding rule.
