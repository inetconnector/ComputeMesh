# Telemetry Service

**Status:** standalone production telemetry/observability service planned; bounded execution/network evidence and measured-feedback foundations are implemented.

## Purpose

Collect privacy-minimized operational evidence for performance, reliability, capacity and debugging without making telemetry the source of truth for money or job state.

## Current implemented foundations

Current public components already emit/retain bounded evidence such as:

- node profiles and benchmark observations;
- network RTT/throughput and controlled relay metrics;
- shared-runtime request/prefill/decode timing and correctness digests;
- execution evidence and authenticated provider attestations;
- bounded failure/recovery records;
- durable verified-outcome delivery to the private control plane.

The private control plane stores verified performance observations and uses them as private prediction/trust inputs. That private data store is not a public telemetry service and must not be exposed as one.

## Responsibilities of the future standalone service

- metrics ingestion
- structured operational events
- traces
- network observations
- benchmark history
- availability history
- dashboards/alerts
- privacy/cardinality/retention policy

## Non-goals

- raw prompt/output logging by default
- authoritative financial balances
- authoritative job-state mutation
- unbounded crash dumps
- exposing private ranking/reputation/fraud features

## Canonical interfaces

- public service/node exporters
- operations/read models
- private performance/control-plane ingestion where explicitly authorized

## Current readiness gap

A consolidated production telemetry service, retention/query layer, RBAC, alerting and HA pipeline are still future work. Existing evidence files/databases and private feedback are intentionally narrower and should not be relabeled as a complete observability platform.

## Required tests / evidence

- duplicate events/idempotent ingestion
- schema/version handling
- redaction/privacy lint
- bounded cardinality and payload size
- retention/deletion policy
- cross-account/operator authorization
- no raw prompt/output leakage by default

## Security and reliability rules

- Treat external inputs as untrusted.
- Use bounded messages/resources and bounded diagnostic text.
- Preserve idempotency for retryable ingestion/state changes.
- Keep private control-plane data private.
- Emit structured errors/metrics without raw prompt/output content.
- Do not widen the V1 arbitrary-code boundary without an accepted ADR.

See `docs/CURRENT_STATUS.md`, `runtime/llama/README.md`, `runtime/network/README.md` and `services/orchestrator/README.md` for the currently implemented evidence paths.
