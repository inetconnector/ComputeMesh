# Protocol Package

**Status:** M0 transport-neutral control-envelope reference implemented; no network transport binding yet.

## Purpose

Machine-readable protocol schemas, base control-message semantics, compatibility checks, structured errors, future generated clients, and examples.

## Current implementation

- `control.py` parses the common control envelope defined in `PROTOCOL.md`;
- rejects unknown/missing base-envelope fields;
- enforces protocol-major compatibility while leaving minor capabilities negotiable;
- validates identifiers, revision shape, RFC3339 timestamps, expiry, and bounded clock skew;
- emits structured machine-readable errors;
- does **not** authenticate/authorize actors or interpret message payloads;
- does **not** select gRPC, QUIC, HTTP/2, or another wire transport.

Machine-readable M0 schemas now include the common control envelope and structured error in addition to node/model/job/reservation contracts.

## Test

Install the current schema-validation dependency, then run:

```powershell
python -m pip install -r requirements-dev.txt
python -m unittest discover -s protocol/tests -v
```

Current local verification before publication: **10/10 tests passing**, including schema validation, protocol-major mismatch, expiry, clock skew, unknown fields, and structured-error output.

## Non-goals

- transport-specific business semantics;
- authentication or authorization before the node-identity design is selected;
- accepting arbitrary fields for forward compatibility in security-sensitive base envelopes;
- treating a higher minor version as automatic permission to use new capabilities.

## Next step

Add concrete message/payload schemas and handlers for the first M0 node/orchestrator operations, then bind them to authenticated sessions after ADR 0005 is sufficiently specified.
