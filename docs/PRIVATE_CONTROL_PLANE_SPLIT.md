# ComputeMesh public/private architecture split

## Objective

Keep the provider edge interoperable and auditable while ensuring that cloning the public repository does not reproduce the commercially valuable ComputeMesh network.

Important: code already published in Git history must be treated as permanently disclosed. This split protects future implementation work, operational datasets, network effects, and proprietary optimization logic; it does not make previously public code secret again.

## Repository roles

### Public repository: `ComputeMesh`

Keep only code required for providers, clients, interoperability, reproducible research, and protocol compatibility.

Public candidates:

- `protocol/` — wire schemas, node identity primitives, message contracts
- `runtime/llama/` — provider/runtime adapters and reproducible shared-inference harnesses, after removing control-plane-specific policy imports
- `runtime/network/` — public transport/measurement interfaces and lab relay
- `tools/benchmark/` — node-side benchmark collection and signed evidence formats
- provider-side portions of `apps/node/`, setup/install tooling, SDKs
- public model/evidence schemas and compatibility fixtures

### Private repository: proposed `ComputeMesh-ControlPlane`

Move new and commercially sensitive implementations here. Existing public implementations should be treated as disclosed reference versions and replaced over time with private successors.

Private candidates:

- production scheduler scoring and topology optimization
- historical performance model and feature engineering
- provider reputation/trust graph
- fraud/anomaly detection
- global network inventory and demand/supply forecasting
- dynamic pricing, take-rate optimization, quote generation
- settlement policy, payout routing and marketplace economics
- production gateway orchestration and retry policy
- production control-plane session registry and dispatch policy
- customer/provider matching and marketplace ranking
- proprietary model/cache placement policy
- operational telemetry aggregation and datasets

Likely current paths to migrate or supersede privately:

- `services/scheduler/placement.py` (public version becomes reference feasibility planner only)
- `services/scheduler/multi_gpu_planner.py`
- `services/scheduler/health_monitor.py` policy layer
- `services/scheduler/model_cache_manager.py` policy layer
- `services/orchestrator/live_shared_runtime.py`
- `services/orchestrator/live_shared_backend.py`
- production portions of `services/orchestrator/*`
- `services/billing/*` beyond public accounting schemas/interfaces
- production gateway policy in `services/gateway/*`
- future reputation/fraud/pricing services

## Boundary rule

Public code MUST NOT import private implementation packages. Communication crosses one of these contracts only:

1. versioned HTTPS/gRPC API
2. signed control-plane protocol messages
3. versioned JSON/Protobuf schemas
4. provider-side plugin interface

The private control plane may depend on the public protocol package; the public package must never depend on the private repository.

## Recommended service boundaries

### Placement API

Input: model identity, constraints, authenticated node capability summaries, network evidence identifiers.

Output: opaque `placement_decision_id`, selected provider IDs, layer ranges/tensor split, lease requirements, expiration, signed decision envelope.

Do NOT expose: candidate ranking scores, proprietary feature weights, performance model internals, global supply state, demand forecasts, or learned coefficients.

### Quote API

Input: model/request class and customer policy.

Output: price quote, expiration and quote ID.

Do NOT expose: provider clearing prices, demand curves, take-rate logic or internal margins.

### Reputation API

Public/provider-visible output should be coarse eligibility/tier information. Keep raw features, graph relationships, fraud rules and model weights private.

### Settlement API

Public components submit signed execution evidence. The private service validates eligibility and produces an immutable settlement result. Provider payout policy and fraud holds remain private.

## Anti-clone design principles

- Never ship production scoring weights or learned models to providers.
- Never place the global provider/customer graph in a client-accessible database.
- Use opaque decision IDs rather than returning internal ranking traces.
- Keep training data, benchmark history, fraud labels and network-wide telemetry in private storage.
- Sign placement/quote/settlement responses so public agents can verify authenticity without possessing decision logic.
- Rate-limit and minimize introspection endpoints to avoid trivial black-box model extraction.
- Do not rely on obfuscation; assume public binaries can be reverse engineered.
- Keep secrets and signing keys outside source control in managed secret storage/HSM/KMS.

## Licensing/IP

A license cannot make already published source secret. For future code, choose intentionally between:

- true open-source components (for adoption/interoperability), and
- proprietary/source-available components whose license forbids operating a competing hosted/network service, if that business restriction is desired.

Have specialist counsel review the final license, CLA/contributor policy, trademark terms, and dependency-license compatibility before release.

## Migration phases

### Phase 0 — stop leakage

- no new production scheduler/reputation/pricing/fraud logic merged to public `main`
- no production datasets, coefficients, provider/customer graph data, private API keys or signing material committed publicly
- require architecture/IP review for new `services/scheduler`, `services/billing`, and production orchestration changes

### Phase 1 — dependency inversion

Create public interfaces for placement, quote, reputation, settlement and provider-control operations. Replace direct imports of production policy with adapters.

### Phase 2 — private successors

Build the new production implementations only in the private control-plane repository. Keep the current public implementations as reference/M1 research implementations until callers are switched.

### Phase 3 — public cleanup

After all public callers use interfaces, remove or freeze disclosed production-like implementations from the public default branch. Add clear `REFERENCE_ONLY` notices where historical code remains.

### Phase 4 — operational moat

Keep network-wide benchmark history, reliability histories, learned placement data, fraud outcomes, pricing history and demand/supply telemetry private. These datasets become the main optimization moat.

## What cannot be guaranteed

No architecture can prevent a well-funded GPU operator from writing a competing network or using AI to implement similar ideas. The realistic objective is to make a clone start without ComputeMesh's private optimization code, trusted identities, accumulated reputation, marketplace liquidity, operational data, brand, customers, provider relationships and signed production control plane.
