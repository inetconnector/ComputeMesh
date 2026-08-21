# ComputeMesh Tests

Component unit tests live beside their code; this directory remains reserved for future cross-component/distributed/chaos tests.

## Simplest Windows path

Double-click:

```text
setup\TESTS.cmd
```

It prepares the local `.venv`, installs `requirements-dev.txt`, and runs the current benchmark, orchestrator, protocol, and setup test suites.

Manual equivalent:

```powershell
python -m pip install -r requirements-dev.txt
python -m unittest discover -s tools/benchmark/tests -v
python -m unittest discover -s services/orchestrator/tests -v
python -m unittest discover -s protocol/tests -v
python -m unittest discover -s setup/tests -v
```

## Future system-test scope

- two-node end-to-end inference;
- duplicate command/replay;
- node loss/reconnect;
- artifact corruption;
- activation transport under latency/jitter/loss;
- billing/security invariants.

No production system-test harness exists yet; the one-click test launcher only orchestrates the implemented local suites.
