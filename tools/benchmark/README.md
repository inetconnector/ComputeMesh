# M0 benchmark harness

This is the first executable ComputeMesh engineering artifact. It is intentionally small: it captures a reproducible node inventory envelope before performance benchmarks and runtime integration are added.

## Run

```powershell
python tools/benchmark/benchmark.py --dry-run
python tools/benchmark/benchmark.py --node-id lab-node-a --profile-revision 1
```

Default output goes to `artifacts/benchmark/`, which is ignored by Git.

## Test

```powershell
python -m unittest discover -s tools/benchmark/tests -v
```

## Current measurements

The M0 collector records:

- OS/release/architecture;
- Python version;
- CPU model/logical cores where available;
- total/available physical memory;
- NVIDIA GPU name, VRAM and driver version when `nvidia-smi` is available;
- collection elapsed time.

It deliberately does **not** collect hostnames, GPU UUIDs, prompts, outputs, or other unnecessary identifiers.

## Next benchmark families

In order:

1. host/device memory bandwidth;
2. representative GEMM/quantized matmul;
3. local runtime prefill/decode;
4. activation-transfer microbenchmark;
5. RTT/jitter/throughput between lab nodes;
6. artifact preparation/load;
7. failure/reconnect injection.

The collector has no third-party Python dependency. Full JSON-Schema validation can be added to CI once the project pins a validation toolchain.
