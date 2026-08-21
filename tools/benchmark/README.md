# M0 benchmark harness

The benchmark directory contains three executable M0 tools:

- `benchmark.py` — reproducible node inventory capture;
- `network_benchmark.py` — application-level TCP path measurement for controlled lab/LAN experiments;
- `llama_bench_adapter.py` — run or import current llama.cpp `llama-bench` JSON/JSONL and convert prompt-processing/decode measurements into ComputeMesh benchmark records.

## Inventory capture

```powershell
python tools/benchmark/benchmark.py --dry-run
python tools/benchmark/benchmark.py --node-id lab-node-a --profile-revision 1
```

The inventory collector records OS/release/architecture, Python version, CPU/logical cores, physical memory, NVIDIA GPU name/VRAM/driver when `nvidia-smi` is available, and collection time. It deliberately excludes hostnames, GPU UUIDs, prompts, outputs, and unnecessary identifiers.

## TCP network microbenchmark

The server defaults to loopback and has **no authentication or encryption**. Do not expose it to the public internet. For a two-machine lab, bind it only on a trusted LAN interface and restrict the port with the host firewall.

On node B:

```powershell
python tools/benchmark/network_benchmark.py server --bind 0.0.0.0 --port 43191 --once
```

On node A:

```powershell
python tools/benchmark/network_benchmark.py client --host <NODE-B-LAN-IP> --port 43191 --profile-revision 1
```

The client measures TCP connection setup, small-frame RTT p50/p95, upload/download throughput p50, and raw samples. Results conform to `benchmark_result.schema.json`.

## llama.cpp prefill/decode adapter

The adapter uses `llama-bench` prompt-processing (`-p`) and generation (`-n`) rows separately. It accepts JSON arrays/objects and JSONL. From these rows it emits two ComputeMesh results:

- `llama_cpp_prefill` — prompt tokens, average prefill elapsed time, average/stddev tokens/s;
- `llama_cpp_decode` — generated tokens, average decode elapsed time, average/stddev tokens/s, and average inter-token milliseconds.

Run a real local benchmark:

```powershell
python tools/benchmark/llama_bench_adapter.py `
  --llama-bench C:\path\to\llama-bench.exe `
  --model C:\path\to\model.gguf `
  --profile-revision 1
```

Or convert a previously captured upstream JSON/JSONL file without running the model again:

```powershell
python tools/benchmark/llama_bench_adapter.py `
  --parse-file artifacts\raw\llama-bench.json `
  --profile-revision 1
```

Defaults are 512 prompt tokens, 128 generated tokens, and five repetitions. Extra upstream flags can be forwarded with repeated `--extra-arg` options.

Privacy rule: the converted ComputeMesh metrics keep the model **file name**, but not its complete local filesystem path. Raw prompt/output text is not part of `llama-bench` records produced by this adapter.

`llama-bench` timing does not include the sampling step, so the prefill elapsed value is a benchmark proxy for preparing first-token logits rather than a full application-level TTFT measurement. Application/server TTFT must be measured separately later.

## Test

```powershell
python -m pip install -r requirements-dev.txt
python -m unittest discover -s tools/benchmark/tests -v
```

Verified before publication of the current M0 blocks:

- inventory collector tests: 3/3 passing;
- TCP network benchmark tests: 4/4 passing, including loopback and result-schema validation;
- llama-bench adapter tests: 6/6 passing, including JSON/JSONL parsing, prefill/decode conversion, inter-token calculation, and result-schema validation.

No real cross-node or real-model performance result is committed as evidence yet.

## Next benchmark families

1. run inventory/network/llama-bench measurements on the real two-node lab;
2. application-level TTFT and streamed inter-token latency;
3. host/device memory bandwidth;
4. representative GEMM/quantized matmul where the runtime does not already expose sufficient evidence;
5. activation-payload transfer sizes representative of stage boundaries;
6. controlled latency/jitter/loss experiments;
7. artifact preparation/load;
8. failure/reconnect injection.

The benchmark executables use only the Python standard library. JSON-Schema validation in tests/admission uses the project development dependency.
