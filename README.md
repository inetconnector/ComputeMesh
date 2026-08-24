# ComputeMesh

**Languages:** **English** | [Deutsch](README.de.md)

> **Stage:** M0 foundation moving into the first controlled M1 shared-runtime experiment.  
> **Important:** ComputeMesh is **not yet a production distributed-inference product**. The Windows/Linux setup prepares the lab/benchmark workflow that actually exists today; it is not a public provider-node installer.

ComputeMesh explores whether heterogeneous computers can cooperate as one model-aware AI inference fabric. The long-term goal is simple: choose a model and policy, while ComputeMesh handles feasibility, placement, preparation, execution, failures, verification, and auditable accounting.

## Fastest way to try the lab tooling

Clone/download the repository and use the launcher for your OS:

**Windows:** double-click `SETUP.cmd`  
**Linux:** run `./setup.sh` (or `bash setup.sh` if the executable bit was lost).

Both launchers expose the same simple menu for profile capture, trusted-LAN RTT/throughput measurement, local llama.cpp benchmarking, and the current complete local test set. New network measurements also carry the local Lab Setup node ID and, when the peer uses the current benchmark server, its self-reported Lab Setup node ID. Model weights are never downloaded automatically.

For the current two-machine M1 evidence handoff, the worker can create a bounded evidence ZIP with `setup\EVIDENCE-EXPORT.cmd` on Windows or `bash setup/EVIDENCE-EXPORT.sh` on Linux. The coordinator can validate/import that ZIP and build the current experiment bundle with `setup\BUILD-BUNDLE.cmd` or `bash setup/BUILD-BUNDLE.sh`. Once that bundle recommends `shared_experiment`, start the trusted-LAN RPC worker with `setup\SHARED-WORKER.cmd` / `bash setup/SHARED-WORKER.sh` and run the bound baseline→relay→shared→compare→proof flow with `setup\SHARED-PROOF.cmd` / `bash setup/SHARED-PROOF.sh`. The ZIP does not contain GGUF weights or llama.cpp binaries.

The detailed two-computer walkthrough is in [setup/README.md](setup/README.md).

## Current implementation

Implemented foundations now include:

- cross-platform Windows/Linux Lab Setup;
- inventory, TCP network, and llama.cpp `llama-bench` measurement tooling;
- bounded GGUF-v3 inspection and conservative model-manifest generation with artifact-derived architecture, layer count, SHA-256 and size;
- a bounded standard-library Lab evidence export/import path with file-size/count limits, SHA-256 verification, traversal/symlink rejection and atomic peer import;
- a fail-closed M1 experiment-bundle builder that selects one coherent current two-node evidence set and embeds the resulting placement decision with source-document digests;
- Draft-2020-12 machine-readable state/control contracts;
- deterministic Job/Reservation semantics and transactional SQLite reference persistence;
- strict transport-neutral control envelopes and durable initial handlers;
- authentication-gated node-session semantics and strict initial wire binding;
- M1 reference node identity `computemesh-ed25519-v1` with enrollment/key-rotation/revocation reference state;
- a controlled llama.cpp RPC **research harness** for the first M1 shared-runtime experiment;
- a fail-closed one-command **physical shared-trial runner** that revalidates the bundle/model/devices, executes the planner-selected split through the relay, checks correctness, and emits the bound proof artifact;
- a loopback-only TCP **measurement relay** for opaque RPC byte accounting, deterministic userspace delay/jitter, and controlled disconnect experiments;
- a deterministic M1 **two-node placement planner** that generates explainable local/shared feasibility candidates from current profiles, model manifest, llama-bench evidence and network measurements without inventing distributed-performance numbers;
- a public portal crawl package for `computemesh.inetconnector.com`, including canonical metadata, `robots.txt`, `sitemap.xml`, local server routes and a Search Console runbook;
- an Ed25519-signed update manifest and visible update controls in the NodeOS web dashboard and Windows/Linux provider apps so nodes can install the newest signed package published on the webserver.

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

Critically, before a correct measured shared-runtime run exists it always leaves:

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

**ADR 0002 remains Proposed.** The harness, transfer/evidence-bundle path and planner prepare the proof; no real correct shared two-node inference result has been recorded yet.

## Runtime network measurement relay

`runtime/network/tcp_relay.py` can sit locally between the llama coordinator and a trusted-private-LAN RPC worker. It listens only on `127.0.0.1`, connects only to literal loopback/RFC1918 IPv4, uses bounded queues, counts opaque bytes separately in both directions, separates setup/active timing, can add reproducible userspace stream delay/jitter, and can force controlled disconnects.

The relay does not parse RPC frames: byte totals include framing/control/data and are **not activation-tensor byte counts**. It also deliberately does not emulate packet loss by dropping TCP bytes. Packet-level loss/reordering remains a separate OS/network-emulation experiment. See [runtime/network/README.md](runtime/network/README.md).

## Verified real-target evidence

Existing physical-target evidence from 2026-08-21 includes:

- Windows target: RTX 3080 Laptop GPU, 16 GiB VRAM, 31.7 GiB RAM;
- Linux target: Debian 13 server, 4 logical CPU cores, 7.8 GiB RAM, CPU-only;
- Windows → internet Linux engineering TCP measurement: RTT p50 `11.884 ms`, p95 `13.369 ms`, upload p50 `42.276 Mbit/s`, download p50 `226.597 Mbit/s`;
- Windows CUDA llama.cpp 7B-Q4 benchmark: prefill `2866.127 tok/s`, decode `76.210 tok/s`;
- Linux CPU llama.cpp 0.5B-Q4 smoke: prefill `12.382 tok/s`, decode `0.201 tok/s`.

The two historical llama.cpp runs used different GGUFs, so they cannot be combined into the current evidence bundle. The internet network result is not a trusted-private-LAN A/B proof and is not distributed shared inference. The relay, evidence-transfer/binding path, GGUF manifest helper, experiment-bundle builder and placement planner currently have cross-platform software evidence, not real two-machine shared-runtime evidence.

## Identity and runtime security boundary

ADR 0005 is accepted **only for the narrow M1 reference implementation**. Missing before public network exposure include provider/user authentication around identity APIs, OS-protected node private-key storage, active-session revocation fan-out, authenticated/encrypted transport, authorization/rate/resource limits, and production service/database operation.

The TCP benchmark's `unauthenticated_server_report_v1` Lab ID is not the ADR-0005 identity proof. The benchmark still has no application authentication/encryption and remains trusted-private-LAN-only.

Upstream llama.cpp RPC remains **trusted-lab-only**. Current ComputeMesh identity/session authentication does not authenticate the upstream RPC socket; neither the local relay, evidence transfer/bundle nor feasibility planner changes that. Never expose the RPC worker to the public internet or an untrusted network.

`confidential_compute` is not a valid guarantee until a concrete trusted-execution/attestation design exists.

## Not implemented yet

There is still no production provider-node installer/service, no completed distributed shared-inference result, no calibrated/production scheduler ranking, no production Gateway/API, no production identity network service, no automatic authenticated evidence transfer/attestation between machines, no complete artifact/runtime/failure wire path, no production runtime transport, no packet-level loss/reordering experiment, no schema-v1 multi-shard GGUF artifact identity/order contract, no fully production-hardened billing/verification/telemetry product stack, and no signed production release/update pipeline.

Payment boundary: the intended real-money purchase path for compute credits is Stripe. The gateway now has a fail-closed Stripe Checkout/Webhook integration path that calls the official Stripe SDK when configured with `STRIPE_API_KEY` and a durable `COMPUTEMESH_STRIPE_SESSION_STORE`; signed webhook crediting additionally requires `STRIPE_WEBHOOK_SECRET`. Checkout metadata/session-store values define the purchased compute-credit amount, so tax-inclusive Stripe totals are not credited as extra compute balance. Provider payout operations now have a Stripe Connect Accounts v2 / Express recipient onboarding path with durable provider accounts, onboarding links, settlement records, transfer idempotency, configurable transfer currency through `COMPUTEMESH_STRIPE_SETTLEMENT_CURRENCY`, and internal ledger payable clearing. Without Stripe configuration it will not issue fake live Checkout or Connect URLs. Real Stripe Connect onboarding still requires the provider/operator's legal entity and KYC details; a German UG cannot be truthfully completed in Stripe until it is founded and registered. MetaMask/EVM wallet handling in the current provider UI is only for selecting a provider payout destination address for earnings from contributed compute power; wallets are not used to buy compute credits or to charge customers.

## Immediate path

```text
same complete GGUF + fresh profiles/llama-bench from one matching llama.cpp build on both nodes
        ↓
bound trusted-LAN coordinator→worker path evidence
        ↓
artifact-derived single-GGUF model manifest
        ↓
worker evidence ZIP → verified coordinator import
        ↓
fail-closed current two-node experiment bundle
        ↓
embedded conservative placement candidate
        ↓
local deterministic llama-server baseline
        ↓
explicit local + RPC layer split
        ↓
correctness + timing comparison
        ↓
opaque RPC byte accounting + delay/jitter/disconnect experiments
        ↓
first reproducible correct shared two-node inference
        ↓
calibrate placement prediction/ranking from measured shared evidence
```

## Repository map

```text
ComputeMesh/
├─ SETUP.cmd / setup.sh   # simple Windows/Linux lab entry points
├─ setup/                 # lab orchestration + bounded evidence transfer
├─ tools/benchmark/       # inventory, TCP, llama-bench and GGUF-manifest tools
├─ services/orchestrator/ # durable M0 state/control foundation
├─ services/identity/     # M1 reference enrollment/key registry
├─ services/scheduler/    # M1 evidence bundling + two-node feasibility planning
├─ protocol/              # contracts, session wire binding, Ed25519 verifier
├─ runtime/llama/         # controlled llama.cpp M1 research spike
├─ runtime/network/       # bounded M1 TCP measurement relay
├─ portal/                # public web portal, sitemap and robots policy
├─ docs/                  # specifications and ADRs
└─ state.md               # canonical engineering handoff
```

For engineering details, read `state.md` first, then `IMPLEMENTATION_PLAN.md`, `ARCHITECTURE.md`, `PROTOCOL.md`, `THREAT_MODEL.md`, [docs/SEARCH_INDEXING.md](docs/SEARCH_INDEXING.md), and the ADRs.

## Language synchronization rule

`README.md` and `README.de.md` are synchronized project entry points and must be updated together for every public-facing change.

## License

All rights reserved until an explicit license is selected and published. Repository visibility does not grant open-source rights.
