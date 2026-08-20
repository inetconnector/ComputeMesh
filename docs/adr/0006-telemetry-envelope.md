# ADR 0006: Telemetry Event Envelope

- **Status:** Proposed
- **Date:** 2026-08-20

## Proposed decision

All telemetry events use a versioned envelope with:

- event ID;
- schema version;
- event type;
- timestamp;
- source service/node;
- job/attempt/placement references when applicable;
- monotonic or sequence metadata where useful;
- structured payload.

Default payloads MUST NOT contain raw prompt/output text.

Telemetry events are observational and cannot directly create financial balance changes. Billing consumes explicitly accepted metering events.

## Verification

- duplicate telemetry does not duplicate metering;
- unknown optional fields are tolerated;
- oversized fields rejected;
- privacy lint/test detects prohibited content keys.
