# M0 benchmark harness

The benchmark directory contains the underlying engineering tools used by the Windows/Linux Lab Setup.

## Normal users: use setup

Windows: double-click `SETUP.cmd`.

Linux:

```bash
./setup.sh
```

The setup handles Python/`.venv`, random node ID, profile revisions, result folders, private-LAN guidance, llama.cpp selection/download, and short summaries. See `setup/README.md` / `setup/README.de.md` for the two-computer walkthrough.

The Python commands below remain available for engineering, automation, and debugging on both operating systems.

## Tools

- `benchmark.py` — reproducible node inventory capture;
- `network_benchmark.py` — application-level TCP path measurement for controlled lab/LAN experiments;
- `llama_bench_adapter.py` — run/import llama.cpp `llama-bench` JSON/JSONL and convert prompt-processing/decode measurements into ComputeMesh benchmark records.

## Inventory capture

```bash
python tools/benchmark/benchmark.py --node-id lab-node-a --profile-revision 1
```

Records OS/architecture, Python, CPU/logical cores, physical memory, NVIDIA GPU name/VRAM/driver when available, and collection time. Hostnames, GPU UUIDs, prompts, outputs, and unnecessary identifiers are excluded.

## TCP network microbenchmark

Manual server on a trusted LAN:

```bash
python tools/benchmark/network_benchmark.py server \
  --bind <PRIVATE-LAN-IP> \
  --port 43191 \
  --node-id lab-node-b \
  --once
```

Manual client:

```bash
python tools/benchmark/network_benchmark.py client \
  --host <SERVER-LAN-IP> \
  --port 43191 \
  --profile-revision 1 \
  --local-node-id lab-node-a \
  --expected-peer-node-id lab-node-b
```

`--expected-peer-node-id` is optional. When the server supplies `--node-id`, a newer client queries it before measurement and records:

- `conditions.local_node_id` for the client Lab Setup identity when supplied;
- `conditions.peer_node_id` for the server-reported Lab Setup identity;
- `conditions.peer_identity_binding = unauthenticated_server_report_v1`.

The peer report is deliberately bounded and content-free. It improves experiment traceability but is **not authenticated identity**. A legacy server that does not implement the identity query remains measurable when `--expected-peer-node-id` is omitted.

The client measures TCP connection setup, small-frame RTT p50/p95, upload/download throughput p50, and raw samples. Results conform to `benchmark_result.schema.json`.

**Security:** this benchmark protocol has no authentication or encryption. Do not expose it to the public internet. Windows Setup uses a temporary `Private`/`LocalSubnet` rule; Linux Setup uses a detected RFC1918 bind and temporary `firewalld`/`ufw` rule when that supported firewall frontend is active. Manual runs must provide equivalent protection themselves. The optional lab-node ID exchange does not change this boundary.

## llama.cpp prefill/decode adapter

Cross-platform form:

```bash
python tools/benchmark/llama_bench_adapter.py \
  --llama-bench /path/to/llama-bench \
  --model /path/to/model.gguf \
  --profile-revision 1
```

Windows paths work equally through Python/PowerShell.

The adapter emits:

- `llama_cpp_prefill` — prompt tokens, average prefill elapsed time, average/stddev tokens/s;
- `llama_cpp_decode` — generated tokens, average decode elapsed time, average/stddev tokens/s, and average inter-token milliseconds.

The converted metrics keep the model file name but not its full local filesystem path. `llama-bench` timing excludes sampling, so the prefill value is a benchmark proxy rather than full application TTFT.

## Tests

Windows: `setup\TESTS.cmd`  
Linux: `./setup/TESTS.sh`

Benchmark coverage includes inventory, legacy and identity-capable TCP loopback paths, peer mismatch handling, bounded node IDs, result-schema validation, and llama-bench JSON/JSONL conversion. Exact current test counts are recorded in `state.md` after cross-platform validation.

Linux launcher/integration tests live under `setup/tests/`. Real cross-node shared-runtime performance evidence is still pending.
