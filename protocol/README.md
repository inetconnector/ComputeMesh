# Protocol Package

**Status:** M0 transport-neutral control envelope plus the first documented message-specific payload contracts/handlers implemented; no authenticated network transport binding yet.

## Purpose

Provide machine-readable protocol contracts, base control-message semantics, compatibility checks, structured errors, and transport-neutral message validation without coupling business semantics to gRPC, QUIC, HTTP, or another transport.

## Current implementation

### Common envelope

`control.py`:

- parses the common control envelope from `PROTOCOL.md`;
- rejects unknown/missing security-sensitive base fields;
- enforces protocol-major compatibility;
- validates identifiers, revision shape, RFC3339 timestamps, expiry, and bounded clock skew;
- emits structured machine-readable errors;
- does not authenticate or authorize actors.

### Initial message payload contracts

`message_contracts.py` and `protocol/schemas/` currently implement exactly three message payloads already defined by `PROTOCOL.md`:

- `ReserveCapacity` — requires `lease_expires_at`;
- `CommitReservation` — requires `job_id` and `stage_id`;
- `CancelJob` — requires a reason and `cutoff_policy=stop_new_billable_work`.

Unknown message types are not silently accepted. Expanding this set requires a matching protocol/schema update rather than inventing wire operations in service code.

### Durable dispatch

The corresponding transport-neutral application handlers live in `services/orchestrator/handlers.py`. They bind envelope `request_id` to the durable SQLite idempotency store and fingerprint the message type + payload. `CommitReservation` also persists job/stage binding atomically with the state transition.

## Test

```powershell
python -m pip install -r requirements-dev.txt
python -m unittest discover -s protocol/tests -v
```

Latest complete local protocol verification: **15/15 passing**, covering the existing envelope/schema tests plus the new message-specific payload contracts.

## Non-goals / remaining work

- no transport selection yet;
- no authentication or authorization yet;
- no claim that a syntactically valid `actor_id` is trusted;
- no automatic capability permission from a higher minor version;
- no arbitrary forward-compatible fields in security-sensitive base contracts;
- no handlers yet for NodeHello/Auth/Profile, artifact/runtime execution, results, verification, drain, heartbeat, or other later protocol operations.

## Next step

Implement authenticated node-session semantics once ADR 0005 is sufficiently specified, then add the minimum remaining message contracts required by the chosen M1 runtime spike.
