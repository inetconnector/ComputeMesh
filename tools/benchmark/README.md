# M0 benchmark harness

The benchmark directory contains the underlying engineering tools used by the Windows Lab Setup.

## Normal Windows users: use the setup

From the repository root, **double-click `SETUP.cmd`**. It handles Python, `.venv`, node IDs/profile revisions, result folders, safe LAN guidance, file selection, and short summaries.

See `setup/README.md` / `setup/README.de.md` for the two-computer walkthrough.

The direct Python commands below remain available for engineering, automation, and debugging.

## Tools

- `benchmark.py` — reproducible node inventory capture;
- `network_benchmark.py` — application-level TCP path measurement for controlled lab/LAN experiments;
- `llama_bench_adapter.py` — run/import llama.cpp `llama-bench` JSON/JSONL and convert prompt-processing/decode measurements into ComputeMesh benchmark records.

## Inventory capture

```powershell
python tools/benchmark/benchmark.py --node-id lab-node-a --profile-revision 1
```

Records OS/architecture, Python, CPU/logical cores, physical memory, NVIDIA GPU name/VRAM/driver when available, and collection time. Hostnames, GPU UUIDs, prompts, outputs, and unnecessary identifiers are excluded.

## TCP network microbenchmark

Manual server on a trusted LAN:

```powershell
python tools/benchmark/network_benchmark.py server --bind <PRIVATE-LAN-IP> --port 43191 --once
```

Manual client:

```powershell
python tools/benchmark/network_benchmark.py client --host <SERVER-LAN-IP> --port 43191 --profile-revision 1
```

The client measures TCP connection setup, small-frame RTT p50/p95, upload/download throughput p50, and raw samples. Results conform to `benchmark_result.schema.json`.

**Security:** this benchmark protocol has no authentication or encryption. Do not expose it to the public internet. The Windows Setup adds a temporary `Private`/`LocalSubnet` firewall rule and binds to a specific private address; manual runs must provide equivalent protection themselves.

## llama.cpp prefill/decode adapter

```powershell
python tools/benchmark/llama_bench_adapter.py `
  --llama-bench C:\path\to\llama-bench.exe `
  --model C:\path\to\model.gguf `
  --profile-revision 1
```

Or convert existing upstream JSON/JSONL:

```powershell
python tools/benchmark/llama_bench_adapter.py `
  --parse-file artifacts\raw\llama-bench.json `
  --profile-revision 1
```

The adapter emits:

- `llama_cpp_prefill` — prompt tokens, average prefill elapsed time, average/stddev tokens/s;
- `llama_cpp_decode` — generated tokens, average decode elapsed time, average/stddev tokens/s, and average inter-token milliseconds.

The converted metrics keep the model file name but not its full local filesystem path. `llama-bench` timing excludes sampling, so the prefill value is a benchmark proxy rather than full application TTFT.

## Tests

Normal Windows path: double-click `setup/TESTS.cmd`.

Manual path:

```powershell
python -m pip install -r requirements-dev.txt
python -m unittest discover -s tools/benchmark/tests -v
```

Current benchmark unit evidence remains:

- inventory: 3/3;
- TCP benchmark: 4/4, including loopback + result-schema validation;
- llama-bench adapter: 6/6, including JSON/JSONL conversion + result-schema validation.

Real cross-node and target-model/GPU evidence is still pending.
