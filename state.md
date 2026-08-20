# ComputeMesh State

Last updated: 2026-08-20

## Current Status

The workspace has been bootstrapped from `ComputeMesh_Blueprint_v1.0.pdf`. Before this work, the project directory contained only the PDF and was not a Git repository. `README.md` and `state.md` did not exist.

The repository now contains planning and architecture documentation plus the initial blueprint-aligned directory structure. No production code has been implemented yet.

## Source Material

Primary source:

- `ComputeMesh_Blueprint_v1.0.pdf`

PDF inspection performed:

- extracted 23 pages of text to `tmp/pdfs/ComputeMesh_Blueprint_v1.0_extracted.txt`
- rendered pages to PNGs under `tmp/pdfs/`
- visually inspected representative pages 1, 13, and 22
- Poppler metadata reported 23 pages, letter page size, unencrypted PDF, no forms, PDF 1.7

`tmp/` is ignored by Git and should remain an intermediate workspace only.

## Branch and Git Situation

Local Git repository initialized on branch `main`.

Remote:

- `origin`: `https://github.com/inetconnector/ComputeMesh.git`
- GitHub repository: `inetconnector/ComputeMesh`
- Visibility: private at creation time

The bootstrap repository has been committed and pushed to `origin/main`.

Initial bootstrap commit:

- `6e8d9fe` - `docs: bootstrap ComputeMesh implementation plan`

## Files Created

Root documents:

- `README.md`
- `IMPLEMENTATION_PLAN.md`
- `ARCHITECTURE.md`
- `PROTOCOL.md`
- `THREAT_MODEL.md`
- `SECURITY.md`
- `CONTRIBUTING.md`
- `LICENSE`
- `.gitignore`
- `state.md`

ADR documents:

- `docs/adr/0000-adr-template.md`
- `docs/adr/0001-bootstrap-from-blueprint.md`

Directory READMEs:

- `apps/node/README.md`
- `apps/desktop/README.md`
- `apps/dashboard/README.md`
- `apps/admin/README.md`
- `services/gateway/README.md`
- `services/scheduler/README.md`
- `services/registry/README.md`
- `services/billing/README.md`
- `services/verification/README.md`
- `services/telemetry/README.md`
- `runtime/cuda/README.md`
- `runtime/llama/README.md`
- `runtime/vllm/README.md`
- `runtime/network/README.md`
- `protocol/README.md`
- `sdk/README.md`
- `models/README.md`
- `tests/README.md`
- `deploy/README.md`
- `research/README.md`

## Architecture and Data Flow

ComputeMesh is planned as a distributed AI execution layer with strict separation of control plane and data plane.

Control plane:

- gateway
- scheduler
- registry
- billing
- verification
- telemetry
- identity and node enrollment
- topology and reputation

Data plane:

- shard transfer
- activation and KV-cache transport
- inference worker execution
- result streaming
- failover route updates
- verification traces

The scheduler uses hardware profiles, model manifests, topology data, network metrics, reliability, privacy tier, price, and failure risk to place model shards or experts.

## Important Design Constraints

- V1 must not run arbitrary customer code on provider machines.
- V1 starts with fiat billing and an internal ledger, not a token.
- Windows is the first target platform for the provider node.
- Communication cost is a first-class scheduling resource.
- Dense WAN pipeline inference is unproven and must be measured early.
- MoE and expert routing are strategic fallback and long-term differentiation paths.
- Every meaningful architecture decision should be recorded as an ADR.
- `README.md` and `state.md` must stay current after meaningful project changes.

## Planned Technology Direction

- Go for control plane, scheduler, node daemon, networking, registry, and billing
- C++/CUDA for performance-critical runtime work
- Python for ML systems research, benchmarks, and experiments
- TypeScript/React for desktop and web UI
- PostgreSQL for durable business, topology, ledger, and audit data
- QUIC and gRPC as data-plane candidates to compare

These are provisional until confirmed by ADRs.

## Data Contracts

Planned core entities:

- users
- nodes
- hardware
- benchmarks
- models
- model_shards
- jobs
- job_segments
- payments
- ledger
- reputation
- verification
- sessions
- clusters
- network_metrics

Planned node states:

- OFFLINE
- CONNECTING
- AUTHENTICATING
- BENCHMARKING
- READY
- ASSIGNED
- LOADING
- SERVING
- DRAINING
- FAILED
- QUARANTINED
- BANNED

Planned job states:

- CREATED
- PLANNING
- RESERVING
- DISPATCHING
- RUNNING
- VERIFYING
- COMPLETED
- SETTLED
- RETRY
- REPLAN
- FAILED
- REFUNDED

All state transitions must be idempotent, logged, and recoverable.

## Implemented Behavior

Implemented:

- repository documentation
- implementation plan
- architecture outline
- protocol outline
- threat model
- security policy
- contribution guide
- ADR template and bootstrap ADR
- initial directory structure

Not implemented:

- node daemon
- gateway
- scheduler
- registry
- billing ledger
- verification service
- telemetry service
- runtime integration
- desktop app
- API
- tests
- deployment

## Verification Commands and Results

Commands actually run:

- `pdfinfo` through bundled Poppler: succeeded with 23 pages, unencrypted, no forms
- `pdftoppm` through bundled Poppler: succeeded and rendered page PNGs under `tmp/pdfs/`
- Python `pypdf` extraction: succeeded and produced 34,486 characters across 23 pages
- visual inspection with `view_image`: checked representative rendered pages 1, 13, and 22

No code tests exist yet.

## Known Issues and Risks

- Technical feasibility remains unproven.
- WAN latency may force a pivot away from dense interactive pipeline inference.
- Unit economics cannot be validated until real measurements exist.
- Provider security requires strong signed-worker and update design before alpha.
- Legal review is needed for IP, patentability, trademark, privacy, payment, and terms.
- The license is intentionally pending; public reuse rights are not granted yet.

## Release and Deployment State

No release exists.

No deployment exists.

No public alpha exists.

## Concrete Next Steps

1. Add M0 ADRs for runtime, transport, model manifest, node identity, and telemetry envelope.
2. Define exact benchmark harness schema.
3. Select first two-node lab hardware.
4. Choose first model target and runtime integration path.
5. Prototype node profile schema.
6. Define Gate 1 measurements.
7. Begin QUIC/gRPC transport experiment.
8. Keep `state.md` updated after each meaningful change.
