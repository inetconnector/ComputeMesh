# ComputeMesh

**Languages:** **English** | [Deutsch](README.de.md)

## In Plain Words

ComputeMesh is being built to connect many ordinary computers into one shared AI computer.

The idea is simple:

- People with spare GPU power can offer it.
- People who need AI compute can get suitable power from the network.
- ComputeMesh decides which machine is a good fit for a request.
- Every run should be measured, verifiable and fairly accounted for.

Think of it like a power grid for AI compute: not one giant data center doing everything, but many suitable machines working together.

## Why It Matters

AI needs a lot of compute. At the same time, many GPUs sit unused in gaming PCs, workstations, small servers and offices. ComputeMesh is building the technology to make that power usable later in a secure and measurable way.

The goal: AI compute should not belong only to a few large providers. More people and companies should be able to offer compute, use compute and get paid for it.

## What Works Today

ComputeMesh is currently a lab and pre-production system. It already includes:

- a public website that defaults to German in Germany;
- public live capacity counters based only on fresh authenticated node heartbeats;
- signed Windows and Linux clients with update checks;
- a gateway that can receive AI requests;
- a provider app that lets a machine report available compute;
- early real two-machine llama.cpp experiments;
- measurements for machine performance, network connection and execution;
- security rules so protected jobs do not silently fall back to unsafe machines;
- clear boundaries for what is still research and what is not yet a product promise.

Current signed client/update channel: `v1.2.21` is live at `https://computemesh.inetconnector.com/updates/version.json`.

## What Is Not Promised Yet

ComputeMesh is not yet a finished product for arbitrary public AI workloads. It still needs broader real-world validation across different GPUs, networks and locations.

Confidential AI execution is also not claimed as a finished hardware security guarantee yet. That requires a concrete TEE/GPU-attestation technology with a real verifier. Until then, `CONFIDENTIAL` intentionally fails closed instead of being enabled unsafely.

## Try It Quickly

Clone/download the repository and use the launcher for your OS:

**Windows:** double-click `SETUP.cmd`  
**Linux:** run `./setup.sh` (or `bash setup.sh` if the executable bit was lost).

The menu can inspect the machine, measure the network connection, test local model speed and run the test suite. Model weights are never downloaded automatically.

The detailed two-computer developer walkthrough is in [setup/README.md](setup/README.md). The current public status is in [docs/CURRENT_STATUS.md](docs/CURRENT_STATUS.md). `state.md` is the detailed technical project log.

## Technical Overview

For developers, this means:

- Machines can measure their hardware and local model speed.
- Two machines can run a controlled lab test together on one model execution.
- The gateway can receive requests and send them to suitable providers.
- Providers must enroll and prove their identity.
- Results, measurements and execution evidence are recorded.
- The scheduler must not silently lower the safety level of protected jobs.
- Public jobs can later use matching GPU power globally when the rules allow it.
- Confidential jobs stay blocked until real hardware attestation is implemented.
- The website, downloads and update files are versioned and signed.

The sections below are more technical. They describe the boundaries, security rules and experiment paths for developers and operators.

### Public/private production boundary

`services/scheduler/placement.py` remains the disclosed deterministic **research/reference** feasibility planner described below. It is not the production ranking engine.

Production placement feasibility/ranking, empirical performance state, reputation/fraud eligibility, private recovery selection, pricing/marketplace policy and settlement policy live in the separate private `inetconnector/ComputeMesh-ControlPlane` repository. The public orchestrator sends a bounded live candidate/network snapshot, accepts only a signed/unexpired execution plan, verifies it fail-closed and executes the minimum placement result without receiving private candidate scores or policy internals.

Verified public execution outcomes can be durably delivered to the private feedback path, where private performance/reliability inputs evolve without being serialized back into public placement responses.

### Global mesh trust/privacy policy

PR #55 (`feat(mesh): integrate confidential global mesh policy`, merged as `e410b1d2adb417cf0e79689279b22899258ba13c`) added the public policy layer for global routing without weakening the existing conservative production gate.

- Provider trust is modelled as `OPEN`, `VERIFIED` and `RESTRICTED`.
- Execution privacy is modelled separately as `PUBLIC`, `CONFIDENTIAL` and `CRYPTO_PRIVATE`.
- `PUBLIC` jobs may use a global heterogeneous GPU pool when technical admission, model/runtime/hardware fit, network requirements and job policy all match.
- Region/EEA and customer/contract restrictions remain independent policy predicates.
- The scheduler must not silently downgrade privacy: protected jobs never fall back to `PUBLIC`, never run on `OPEN`, and never run on plaintext-logging nodes.
- `CONFIDENTIAL` and `CRYPTO_PRIVATE` default OFF. Confidential execution requires a concrete technology-specific attestation verifier; TLS, containers, VMs and sharding are explicitly not accepted as confidential computing by themselves.
- Confidential attestation is bound to node identity, nonce, runtime measurement/digest and attested ephemeral public key. Content keys must not enter ordinary gateway/control-plane code; any key-release target must match the attested node, nonce and ephemeral key exchange.

The repository therefore contains policy contracts, schemas, filters and fail-closed tests, but it still does **not** claim real production-ready confidential-inference hardware. A concrete TEE/GPU-attestation technology and verifier must be implemented and enabled before `CONFIDENTIAL` can pass.

## M1 two-node placement and evidence bundle

`services/scheduler/placement.py` is the first machine-readable placement component. It is an **experiment feasibility planner**, not a production scheduler.

It checks:

- node/profile schemas and exact profile revisions;
- draining and stale/future-skewed profiles;
- selected model artifact size against all four llama-bench records;
- `contiguous_layers` permission in the model manifest;
- provider memory fractions plus a conservative planner memory cap;
- a coordinator→worker network measurement whose embedded local/peer Lab IDs are checked when present;
- a model layer count taken from the manifest when present.

It can emit:

- `shared_experiment` when a conservative contiguous two-node layer split is memory-feasible;
- `local_only` when only the coordinator baseline is feasible;
- `no_plan` when current hard constraints/memory evidence allow neither.

The output includes deterministic `decision_id`, contiguous layer ranges, relative `tensor_split` weights, hard-constraint explanations and the measured individual compute/network evidence.

Critically, the public research planner does not invent shared-runtime predictions when it lacks calibrated evidence:

```text
predicted_shared_request_ms = null
predicted_speedup_vs_local = null
```

Current network benchmark records can embed `local_node_id`, `peer_node_id` and `peer_identity_binding`; the current server report is labelled `unauthenticated_server_report_v1`. This removes a manual experiment-bookkeeping step but **does not authenticate the peer**. Older network records and model manifests remain usable through explicit `caller_asserted_v1` peer/layer fallbacks in the direct placement CLI, and embedded evidence must never conflict with a supplied fallback.

For the current real M1 experiment, `services/scheduler/evidence_bundle.py` is deliberately stricter. Given two Lab evidence roots plus the model manifest, it selects the highest coherent profile revision, exact-size prefill/decode runs for one common model basename, requires all four selected llama-bench records across both nodes to carry one identical concrete llama.cpp build number/commit, and selects a correctly directed network record with embedded local/peer IDs. It does **not** allow caller-asserted peer or layer fallbacks. Ambiguous latest runs, multiple node identities, wrong-direction/legacy network evidence, corrupt evidence-looking JSON and model-size mismatches fail closed.

The resulting `experiment_bundle.schema.json` artifact includes the complete validated placement decision plus safe source basenames and SHA-256 of each selected source JSON. Absolute local paths are excluded. The hashes make the selected copied evidence set reproducible, but they are not cryptographic attestation of who originally produced those files. See [services/scheduler/README.md](services/scheduler/README.md).

## Two-machine Lab evidence transfer

`setup/evidence_transfer.py` removes the manual directory-copy step around the bundle builder while deliberately remaining a local trusted-lab utility.

On the worker, the export path scans only the node's Lab JSON tree and writes a ZIP containing recognized profile/benchmark evidence. It excludes model weights, llama.cpp runtime downloads, `config.json`, remembered local paths, and arbitrary files. Each included file is recorded by safe relative path, exact size and SHA-256 in `computemesh-lab-export.json`.

On the coordinator, import is fail-closed: the archive/member count and compressed/uncompressed byte totals are bounded; the member set must match the manifest exactly; encrypted/symlink/traversal entries are rejected; every file is streamed through the declared size and SHA-256 check; and extraction becomes visible only after an atomic temp-directory rename. Re-import verifies the existing tree rather than trusting it. Re-exporting the same evidence at a different time retains the same evidence identity, because the export timestamp is observational metadata rather than part of the content identity.

`setup/lab.py bundle --peer-export ... --model-manifest ...` then hands the verified imported worker tree plus the coordinator's local tree to the stricter current bundle selector. Windows and Linux have direct launchers for the same path. Export/import use only the Python standard library; the small JSON-schema dependency is needed only for bundle construction.

**Boundary:** these hashes detect corruption/change in the copied evidence. They do not authenticate the producer, sign a node, or attest hardware. The transfer path remains a controlled trusted-lab convenience, not production evidence transport.

## GGUF → model manifest

`tools/benchmark/gguf_manifest.py` removes another manual M1 bookkeeping step. For a local little-endian GGUF v3 file it can read bounded standardized metadata and derive:

- `general.architecture`;
- `<architecture>.block_count` as manifest `layer_count`;
- known standardized `general.file_type` quantization labels;
- model name/version/license metadata when present;
- exact local file size and streaming SHA-256 digest.

The helper never executes model code and never loads tensor contents into memory. License/version/quantization facts that are missing or not safely mapped must be supplied explicitly, and allowed partitioning modes are always explicit rather than inferred.

Current llama.cpp split metadata is also recognized. A primary shard with `split.count > 1` can be identified, but schema-v1 manifest generation is deliberately refused because one shard's digest/size does not represent the complete model and schema v1 does not yet encode shard membership/order strongly enough. Merge the complete shard set to one GGUF before generating the current ComputeMesh manifest. See [tools/benchmark/README.md](tools/benchmark/README.md).

## Controlled llama.cpp M1 experiment

`runtime/llama/rpc_spike.py` can discover current llama.cpp devices, record a deterministic local baseline, run an explicit local+RPC `layer` split, and compare the exact same model/prompt by token-ID digest when available (otherwise output digest). It records model/runtime/topology/timing evidence without raw prompt/output persistence. `runtime/llama/shared_trial.py` now composes that narrow first-proof flow into one fail-closed coordinator command: it rechecks bundle freshness and exact GGUF identity, requires the current `llama-server` build number/commit to match the build bound from both nodes' selected llama-bench evidence, preflights current RPC visibility, runs baseline and the planner-selected split through a fresh measurement relay, requires exact correctness, and builds `shared_run_evidence.json`.

The first experiment keeps coordinator HTTP on `127.0.0.1`, restricts RPC to literal loopback/RFC1918 IPv4, uses `--offline`, disables automatic fitting and cache surfaces, and treats upstream RPC only as a trusted-lab implementation detail. The automated runner currently requires an accelerator-backed coordinator rather than inventing local-CPU split semantics. See [runtime/llama/README.md](runtime/llama/README.md).

ADR 0002 has one recorded trusted-lab physical proof in `state.md`, but the harness remains an experiment path. It is not by itself a production runtime or security boundary, and any new topology/model/runtime build needs fresh evidence.

## Runtime network measurement relay

`runtime/network/tcp_relay.py` can sit locally between the llama coordinator and a trusted-private-LAN RPC worker. It listens only on `127.0.0.1`, connects only to literal loopback/RFC1918 IPv4, uses bounded queues, counts opaque bytes separately in both directions, separates setup/active timing, can add reproducible userspace stream delay/jitter, and can force controlled disconnects.

The relay does not parse RPC frames: byte totals include framing/control/data and are **not activation-tensor byte counts**. It also deliberately does not emulate packet loss by dropping TCP bytes. Packet-level loss/reordering remains a separate OS/network-emulation experiment. See [runtime/network/README.md](runtime/network/README.md).

## Verified real-target evidence

Historical physical-target evidence from 2026-08-21 includes:

- Windows target: RTX 3080 Laptop GPU, 16 GiB VRAM, 31.7 GiB RAM;
- Linux target: Debian 13 server, 4 logical CPU cores, 7.8 GiB RAM, CPU-only;
- Windows → internet Linux engineering TCP measurement: RTT p50 `11.884 ms`, p95 `13.369 ms`, upload p50 `42.276 Mbit/s`, download p50 `226.597 Mbit/s`;
- Windows CUDA llama.cpp 7B-Q4 benchmark: prefill `2866.127 tok/s`, decode `76.210 tok/s`;
- Linux CPU llama.cpp 0.5B-Q4 smoke: prefill `12.382 tok/s`, decode `0.201 tok/s`.

Those two historical llama.cpp benchmark runs used different GGUFs, so they cannot be combined into the current evidence bundle. The internet network result is not a trusted-private-LAN A/B proof. Later engineering recorded a narrow physical two-machine shared-runtime proof separately in `state.md`; neither set of evidence is a blanket production claim for other hardware/models/topologies.

## Identity and runtime security boundary

ADR 0005 remains the narrow M1 reference identity decision. The live provider-control path now authenticates enrolled Ed25519 node identities and collects authenticated execution attestations, but production hardening is still incomplete.

Missing before untrusted public-network provider operation include OS-protected node private-key storage, active-session revocation fan-out, complete service authorization/rate/resource controls, hardened production database/HA operation and a production-safe authenticated/encrypted data plane.

The TCP benchmark's `unauthenticated_server_report_v1` Lab ID is not the ADR-0005 identity proof. The benchmark still has no application authentication/encryption and remains trusted-private-LAN-only.

Upstream llama.cpp RPC remains **trusted-network-only**. ComputeMesh provider/session authentication does not make the upstream RPC socket safe for public exposure. Development/operator tooling can contain that socket behind loopback/private networking/SSH tunnels, but RPC itself is not the ComputeMesh production security boundary. Never expose the RPC worker directly to the public internet or an untrusted network.

`confidential_compute` is not a valid product guarantee until a concrete trusted-execution/GPU-attestation technology and verifier exist. The current `CONFIDENTIAL` policy class is intentionally fail-closed by default.

## Remaining product-readiness work

The production **policy boundary** now exists privately, but broad production distributed inference is not yet validated. Remaining gates include:

- run the complete current gateway → private placement → real provider execution → evidence/attestation → private feedback path repeatedly on representative physical GPU pairs;
- controlled LAN delay/jitter/bandwidth/disconnect measurements and real two-site WAN validation;
- calibrate the private production predictor/optimizer from verified measurements rather than assumptions;
- enforce resource reservations/leases at the provider, not only in control-plane state;
- replace/contain the experimental upstream RPC path with a production-safe authenticated/encrypted data plane;
- production node-key storage, revocation/session fan-out and service authorization/resource controls;
- broader adversarial/system/fuzz/failure testing;
- complete production artifact lifecycle including stronger multi-shard identity/order semantics;
- true upstream token streaming/TTFT measurement where required;
- final HA/operations hardening for billing, verification, telemetry and private control-plane persistence.

Payment boundary: the intended real-money purchase path for compute credits is Stripe. The gateway now has a fail-closed Stripe Checkout/Webhook integration path that calls the official Stripe SDK when configured with `STRIPE_API_KEY` and a durable `COMPUTEMESH_STRIPE_SESSION_STORE`; signed webhook crediting additionally requires `STRIPE_WEBHOOK_SECRET`. Checkout metadata/session-store values define the purchased compute-credit amount, so tax-inclusive Stripe totals are not credited as extra compute balance. Provider payout operations now have a Stripe Connect Accounts v2 / Express recipient onboarding path with durable provider accounts, onboarding links, settlement records, transfer idempotency, configurable transfer currency through `COMPUTEMESH_STRIPE_SETTLEMENT_CURRENCY`, and internal ledger payable clearing. Without Stripe configuration it will not issue fake live Checkout or Connect URLs. Real Stripe Connect onboarding still requires the provider/operator's legal entity and KYC details; a German UG cannot be truthfully completed in Stripe until it is founded and registered. MetaMask/EVM wallet handling in the current provider UI is only for selecting a provider payout destination address for earnings from contributed compute power; wallets are not used to buy compute credits or to charge customers.

## Immediate path

```text
current private umbrella checkout + pinned public runtime
        ↓
real enrolled coordinator/worker providers + one matching llama.cpp build/model
        ↓
full authenticated gateway/private-placement/shared-runtime request
        ↓
signed placement verification + real execution evidence + provider attestations
        ↓
durable verified outcome → new private performance observation
        ↓
repeatable controlled LAN delay/jitter/bandwidth/disconnect matrix
        ↓
real WAN/two-site validation
        ↓
calibrate private prediction/ranking from measured evidence
        ↓
provider-enforced leases + production data-plane/key/session hardening
        ↓
widen production scheduling only when gates are met
```

## Repository map

```text
ComputeMesh/
├─ SETUP.cmd / setup.sh   # Windows/Linux public lab entry points
├─ setup/                 # lab orchestration + bounded evidence transfer
├─ apps/node/             # runnable public provider agent + node surface
├─ tools/benchmark/       # inventory, TCP, llama-bench and GGUF-manifest tools
├─ services/gateway/      # authenticated public API/live gateway
├─ services/orchestrator/ # durable state + live execution/recovery/feedback plumbing
├─ services/identity/     # reference enrollment/key registry + live identity backing
├─ services/scheduler/    # public M1 evidence/reference feasibility planning
├─ protocol/              # contracts, session wire binding, Ed25519 verifier
├─ runtime/llama/         # controlled llama.cpp shared-runtime research path
├─ runtime/network/       # bounded network measurement/fault instrumentation
├─ portal/                # public web portal, sitemap and robots policy
├─ docs/                  # current status, specifications, audits and ADRs
└─ state.md               # public historical engineering/evidence handoff
```

For current public status read [docs/CURRENT_STATUS.md](docs/CURRENT_STATUS.md) first, then the nearest component README. Use `state.md` for detailed engineering chronology/evidence and `IMPLEMENTATION_PLAN.md`, `ARCHITECTURE.md`, `PROTOCOL.md`, `THREAT_MODEL.md` and the ADRs for target/history context.

## Language synchronization rule

`README.md` and `README.de.md` are synchronized project entry points and must be updated together for every public-facing change. Current status additionally has synchronized `docs/CURRENT_STATUS.md` and `docs/CURRENT_STATUS.de.md`.

## License

All rights reserved until an explicit license is selected and published. Repository visibility does not grant open-source rights.
