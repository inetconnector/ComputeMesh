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

Both prepare/use repository-local `.venv`, install `requirements-dev.txt`, and run benchmark, orchestrator, protocol, and setup test suites.

Manual equivalent:

```bash
python -m pip install -r requirements-dev.txt
python -m unittest discover -s tools/benchmark/tests -v
python -m unittest discover -s services/orchestrator/tests -v
python -m unittest discover -s protocol/tests -v
python -m unittest discover -s setup/tests -v
```

The Linux setup adds Bash-specific regression coverage; those tests skip automatically when Bash is unavailable (for example on a normal Windows-only Python environment).

## Future system-test scope

- two-node end-to-end inference;
- mixed Windows/Linux node scenarios;
- duplicate command/replay;
- node loss/reconnect;
- artifact corruption;
- activation transport under latency/jitter/loss;
- billing/security invariants.

No production system-test harness exists yet; the launchers only orchestrate the implemented local suites.
