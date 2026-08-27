# ComputeMesh code classification

This file is a migration checklist for the `hardening/private-control-plane-split` branch.

## PUBLIC — keep in `inetconnector/ComputeMesh`

- `protocol/schemas/**`
- `protocol/message_contracts.py`
- provider-facing portions of `protocol/node_identity.py`, `protocol/node_session.py`, `protocol/session_wire.py`
- `runtime/llama/rpc_spike.py` as a research/runtime adapter, subject to upstream llama.cpp licensing
- `runtime/llama/shared_trial.py` and evidence schemas as reproducible M1 research tooling
- `runtime/network/tcp_relay.py` as a lab measurement tool
- `tools/benchmark/**`
- provider hardware detection and installer/bootstrap tooling
- SDK/client contracts and examples

Reason: these maximize provider adoption and interoperability without containing the long-term commercial optimization moat.

## PUBLIC REFERENCE ONLY — freeze, do not evolve into production policy

- `services/scheduler/placement.py`
- `services/scheduler/multi_gpu_planner.py`
- current two-node selection logic
- research performance harnesses

Action: add explicit reference/experimental status and stop adding production scoring features here. New production placement logic belongs only in the private control plane.

## PRIVATE SUCCESSOR REQUIRED

These current public paths reveal useful architecture, but future production versions should be developed privately behind interfaces:

- `services/orchestrator/live_shared_runtime.py`
- `services/orchestrator/live_shared_backend.py`
- `services/orchestrator/shared_request_backend.py`
- production policy within `services/orchestrator/*`
- production gateway routing/placement policy within `services/gateway/*`
- pricing/settlement/payout strategy within `services/billing/*`
- future provider reputation, fraud, abuse and trust scoring
- future marketplace matching/ranking
- future global cache placement and topology optimization

## STRICT PRIVATE — never commit to public repository

- scheduler model weights, coefficients and objective weights
- provider/customer graph and historical job data
- raw reliability/reputation features
- fraud labels, heuristics and detection thresholds
- demand forecasts and supply elasticity models
- provider clearing prices and internal take-rate logic
- per-customer negotiated pricing
- global topology snapshots
- production signing private keys, API credentials, KMS/HSM material
- private prompt/model workload distributions used to train the scheduler
- internal anti-abuse rules

## PRIVATE REPOSITORY LAYOUT

Proposed repository name: `inetconnector/ComputeMesh-ControlPlane` (private).

Suggested tree:

```text
controlplane/
  api/
    placement_service.py
    quote_service.py
    reputation_service.py
    settlement_service.py
  scheduler/
    optimizer.py
    cost_model.py
    topology.py
    performance_model.py
    cache_policy.py
  reputation/
    graph.py
    reliability.py
    fraud.py
  marketplace/
    matching.py
    pricing.py
    supply_demand.py
  settlement/
    policy.py
    payouts.py
    disputes.py
  orchestration/
    dispatcher.py
    recovery.py
    capacity.py
  data/
    feature_store.py
    telemetry_store.py
  adapters/
    public_protocol.py
    provider_control.py
```

## Public/private dependency direction

Allowed:

```text
private-control-plane -> public protocol/sdk
public provider agent -> signed network API
public client SDK -> public gateway API
```

Forbidden:

```text
public repository -> import private Python package
public binary -> embed scheduler weights
public API -> expose candidate scores/features
provider agent -> receive global topology/reputation datasets
```

## Migration safety

Do not delete current public implementations merely to claim secrecy. They are already disclosed. First create interface boundaries, switch production deployment to private successors, then freeze or remove public reference implementations only for maintenance clarity.
