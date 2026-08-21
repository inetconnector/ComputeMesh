# M0 benchmark harness

The benchmark directory now contains two executable M0 tools:

- `benchmark.py` — reproducible node inventory capture;
- `network_benchmark.py` — application-level TCP path measurement for controlled lab/LAN experiments.

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

The client measures:

- TCP connection setup time;
- small-frame RTT p50/p95;
- upload throughput p50;
- download throughput p50;
- raw per-sample values.

Default client transfer size is 16 MiB repeated three times; the server rejects transfers above its configured maximum (64 MiB by default). Results are emitted as `benchmark_result.schema.json`-compatible `tcp_network_path` records below `artifacts/benchmark/`.

## Test

```powershell
python -m unittest discover -s tools/benchmark/tests -v
```

The network benchmark was locally verified with loopback client/server tests, transfer-limit rejection, percentile behavior, and Draft-2020-12 validation of a generated result against the existing benchmark-result schema.

## Next benchmark families

1. host/device memory bandwidth;
2. representative GEMM/quantized matmul;
3. local runtime prefill/decode;
4. activation-transfer payload microbenchmark;
5. multi-condition RTT/jitter/loss experiments;
6. artifact preparation/load;
7. failure/reconnect injection.

Both benchmark executables use only the Python standard library. JSON-Schema validation in tests uses the project development dependency.
