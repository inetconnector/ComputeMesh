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
python -m unittest discover -s runtime/llama/tests -v
python -m unittest discover -s runtime/network/tests -v
python -m unittest discover -s setup/tests -v
```

The Linux setup adds Bash-specific regression coverage; those tests skip automatically when Bash is unavailable (for example on a normal Windows-only Python environment).

The runtime-network suite performs real loopback TCP forwarding tests on the test host. It does not contact public or remote hosts.

## Future system-test scope

- two-node end-to-end inference;
- mixed Windows/Linux node scenarios;
- duplicate command/replay;
- authenticated node loss/reconnect;
- artifact corruption;
- real llama.cpp worker loss/reconnect;
- packet-level latency/jitter/loss/reordering through controlled OS/network emulation;
- billing/security invariants.

The current TCP measurement relay can inject userspace stream delay/jitter and deliberate disconnects, but it is not a packet-loss emulator and is not the production runtime transport.

No production system-test harness exists yet; the launchers only orchestrate the implemented local suites.
