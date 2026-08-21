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

- benchmark tooling;
- durable orchestrator/state;
- protocol/session/identity-verifier contracts;
- identity registry/integration;
- deterministic M1 two-node placement planner;
- llama.cpp M1 runtime-spike harness;
- TCP network measurement relay;
- setup/launcher regressions.

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

The Linux setup adds Bash-specific regression coverage; those tests skip automatically when Bash is unavailable (for example on a normal Windows-only Python environment).

The runtime-network suite performs real loopback TCP forwarding tests on the test host. It does not contact public or remote hosts. Scheduler tests use synthetic contract-valid evidence and do not claim real placement performance.

## Evidence-binding coverage

The current M1 evidence-binding tests additionally enforce:

- current benchmark servers can self-report a bounded Lab node ID;
- legacy benchmark servers remain compatible when an expected peer is not required;
- expected peer-ID mismatches are rejected;
- `peer_node_id` and `peer_identity_binding` are schema-paired;
- Setup passes its own stable random Lab node ID into network server/client commands;
- a placement decision prefers embedded network peer evidence over caller assertions;
- embedded network local/peer IDs must match coordinator/worker profiles;
- caller assertions may support legacy records but may not conflict with embedded evidence;
- optional `model_manifest.layer_count` is preferred over the legacy caller layer count;
- manifest/caller layer-count conflicts are rejected;
- no shared latency/speedup prediction is fabricated from these stronger bookkeeping fields.

`unauthenticated_server_report_v1` remains a traceability label, not an authentication guarantee.

The latest cross-platform suite counts and workflow evidence are recorded in `state.md`.

## Future system-test scope

- fresh trusted-private-LAN A↔B evidence carrying current Lab-ID metadata;
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

No production system-test harness exists yet; the launchers only orchestrate the implemented local suites.
