# M0 benchmark harness

The benchmark directory contains the underlying engineering tools used by the Windows/Linux Lab Setup plus bounded model-artifact helpers used by the M1 placement experiment.

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
- `llama_bench_adapter.py` — run/import llama.cpp `llama-bench` JSON/JSONL and convert prompt-processing/decode measurements into ComputeMesh benchmark records;
- `gguf_manifest.py` — bounded GGUF-v3 metadata inspection and conservative ComputeMesh model-manifest generation.

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

## GGUF model-manifest helper

Inspect the bounded metadata ComputeMesh will use:

```bash
python tools/benchmark/gguf_manifest.py inspect \
  --gguf /path/to/model.gguf
```

Build a schema-v1 model manifest:

```bash
python tools/benchmark/gguf_manifest.py build \
  --gguf /path/to/model.gguf \
  --partitioning contiguous_layers \
  --redistribution-disallowed
```

The helper derives only facts it can establish from the local artifact:

- `general.architecture` → manifest `architecture`;
- `<architecture>.block_count` → manifest `layer_count`;
- standardized `general.file_type` → a known quantization label when mapped;
- `general.name`, `general.version`, `general.license`, and `general.license.link` when present;
- exact local file size and streaming SHA-256 digest.

Missing semantic fields must be supplied explicitly with `--model-id`, `--model-version`, `--license-id`, `--license-source`, or `--quantization`. Partitioning permission is always explicit; the tool never infers that a model license or architecture permits a particular distributed placement mode.

The reader is intentionally bounded and supports little-endian GGUF v3 only. It reads the header/metadata area and streams the artifact hash; it never loads tensor contents into memory or executes model code.

### Split GGUF guardrail

Current llama.cpp `gguf-split` writes ordinary model metadata only to primary shard `split.no = 0`, while every shard carries `split.no`, `split.count`, and `split.tensors.count`. The helper recognizes and validates those fields.

A GGUF with `split.count > 1` can be inspected from its primary shard, but **manifest generation is refused**. ComputeMesh model-manifest schema v1 does not yet encode shard identity/order strongly enough for the tool to claim that one shard digest/size represents the complete model. Merge the complete shard set to one GGUF before generating the current manifest. A file carrying `split.count = 1` remains buildable.

## Tests

Windows: `setup\TESTS.cmd`  
Linux: `./setup/TESTS.sh`

Benchmark coverage includes inventory, GGUF metadata/manifest generation and split-shard rejection, legacy and identity-capable TCP loopback paths, peer mismatch handling, bounded node IDs, result-schema validation, and llama-bench JSON/JSONL conversion. Exact current test counts are recorded in `state.md` after cross-platform validation.

Linux launcher/integration tests live under `setup/tests/`. Real cross-node shared-runtime performance evidence is still pending.
