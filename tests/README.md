# ComputeMesh Tests

Component unit tests live beside their code; this directory remains reserved for future cross-component/distributed/chaos tests.

## Simplest path

Windows:

```text
setup\TESTS.cmd
```

Linux:

```bash
./setup/TESTS.sh
```

Both prepare/use repository-local `.venv`, install `requirements-dev.txt`, and run all current local suites:

- benchmark/model-artifact tooling;
- durable orchestrator/state;
- protocol/session/identity-verifier contracts;
- identity registry/integration;
- deterministic M1 two-node placement and experiment-evidence bundling;
- llama.cpp M1 runtime-spike harness;
- TCP network measurement relay;
- setup/launcher/evidence-transfer regressions.

Manual equivalent:

```bash
python -m pip install -r requirements-dev.txt
python -m unittest discover -s tools/benchmark/tests -v
python -m unittest discover -s services/orchestrator/tests -v
python -m unittest discover -s protocol/tests -v
python -m unittest discover -s services/identity/tests -v
python -m unittest discover -s services/scheduler/tests -v
python -m unittest discover -s runtime/llama/tests -v
python -m unittest discover -s runtime/network/tests -v
python -m unittest discover -s setup/tests -v
```

The Linux setup adds Bash-specific regression coverage; those tests skip automatically when Bash is unavailable (for example on a normal Windows-only Python environment). The cross-platform validation workflow also parses the new evidence PowerShell with the real Windows PowerShell parser.

The runtime-network suite performs real loopback TCP forwarding tests on the test host. It does not contact public or remote hosts. Scheduler/bundle tests use synthetic contract-valid evidence and do not claim real placement performance.

## Evidence-binding, model-artifact, bundle and transfer coverage

The current M1 tests additionally enforce:

- current benchmark servers can self-report a bounded Lab node ID;
- legacy benchmark servers remain compatible when an expected peer is not required;
- expected peer-ID mismatches are rejected;
- `peer_node_id` and `peer_identity_binding` are schema-paired;
- malformed identity-query streams are closed without being resynchronized as valid benchmark frames;
- Setup passes its own stable random Lab node ID into network server/client commands;
- a placement decision prefers embedded network peer evidence over caller assertions;
- embedded network local/peer IDs must match coordinator/worker profiles;
- caller assertions may support the direct legacy planner path but may not conflict with embedded evidence;
- optional `model_manifest.layer_count` is preferred over the legacy caller layer count;
- manifest/caller layer-count conflicts are rejected;
- bounded GGUF-v3 inspection extracts standardized architecture/block-count/model metadata without reading tensor contents into memory;
- generated single-file manifests carry exact SHA-256/size and validate against `model_manifest.schema.json`;
- missing license/version/quantization facts require explicit overrides rather than guesses;
- `split.no`, `split.count`, and `split.tensors.count` must be complete and internally bounded;
- a non-primary llama.cpp split shard is identified as lacking full model metadata;
- schema-v1 manifest generation rejects `split.count > 1` so one shard is never represented as the complete model;
- the current experiment-bundle path selects the highest coherent profile revision per node and ignores older-revision benchmarks;
- bundle llama evidence must use the selected profile revision, exact manifest artifact size, a complete prefill/decode pair and one common model basename across both nodes;
- multiple node IDs or multiple matching model basenames require explicit disambiguation;
- equally recent distinct candidate runs are rejected instead of selected nondeterministically;
- benchmarks timestamped before their selected profile are not accepted for the current bundle;
- the bundle requires a correctly directed coordinator→worker network result with embedded local/peer IDs;
- legacy/caller-asserted network binding cannot produce a current experiment bundle;
- evidence-looking JSON that fails its schema aborts discovery rather than causing silent fallback to older evidence;
- bundle provenance stores safe basenames and SHA-256 of exact source JSON documents, never absolute local paths;
- gateway authentication rejects unregistered `cm_live_...` and `cm_provider_...` tokens by default, requires `COMPUTEMESH_ADMIN_KEY` for admin routes, and accepts Portal/Gateway shared key-store records through `COMPUTEMESH_API_KEY_STORE_PATH`;
- public node telemetry status/dashboard routes require the node's tunnel token instead of returning registered node data to unauthenticated callers;
- bundle and placement identities are deterministic for the same source evidence/policy;
- Lab export excludes GGUF weights, llama.cpp binaries, config and arbitrary non-evidence files;
- the export manifest contains only safe relative evidence paths plus exact size/SHA-256 and does not leak the source root;
- export requires the configured node/profile revision to match the newest captured profile;
- peer ZIP import requires the exact manifest member set and rejects changed bytes, path traversal, symlink/encrypted entries and bounded-size violations;
- extraction is hash-verified before atomic publication, and re-import verifies the existing tree instead of trusting it;
- repeated exports of the same evidence remain one import identity even when their observational `created_at` differs;
- a tampered previously imported tree is detected;
- `setup/lab.py status` starts under `python -S`, proving ordinary setup does not acquire the scheduler's external dependency;
- a complete synthetic worker-export → coordinator-import → current `experiment_bundle.json` round trip succeeds without absolute paths;
- no shared latency/speedup prediction is fabricated from stronger bookkeeping fields.

`unauthenticated_server_report_v1` remains a traceability label, not an authentication guarantee. GGUF manifest generation is local metadata inspection, not model execution or license inference. Export/bundle document hashes identify copied inputs but are not producer authentication or hardware attestation.

The latest cross-platform suite counts and workflow evidence are recorded in `state.md`.

## Future system-test scope

- fresh trusted-private-LAN A↔B evidence carrying current Lab-ID metadata;
- the same complete GGUF benchmarked on both physical nodes;
- real worker evidence ZIP imported by the physical coordinator and bound into one current experiment bundle;
- two-node end-to-end inference;
- scheduler calibration against correct measured shared-runtime evidence;
- mixed Windows/Linux node scenarios;
- duplicate command/replay;
- authenticated node loss/reconnect;
- artifact corruption;
- real llama.cpp worker loss/reconnect;
- packet-level latency/jitter/loss/reordering through controlled OS/network emulation;
- billing/security invariants.

The current TCP measurement relay can inject userspace stream delay/jitter and deliberate disconnects, but it is not a packet-loss emulator and is not the production runtime transport. The current planner is feasibility-only and deliberately does not predict shared speedup before a correct shared run exists.

No production system-test harness exists yet; the launchers only orchestrate the implemented local suites. Latest local validation: `python run_all_tests.py` passed 284/284 tests in 11.39s on 2026-08-26.
