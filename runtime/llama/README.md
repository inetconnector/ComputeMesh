# llama.cpp Runtime Integration

**Status:** M1 research spike harness implemented; no distributed-inference result yet.

## Purpose

Evaluate whether current llama.cpp RPC/device offload is a viable **research baseline** for the first ComputeMesh shared-inference proof. Upstream RPC remains an implementation detail behind the ComputeMesh boundary, not the public node protocol.

## Why this narrow path

Current llama.cpp exposes remote ggml devices through its RPC backend and lets a coordinator use `--rpc`, explicit `--device`, `--split-mode layer`, and `--tensor-split`. Upstream also explicitly warns that the RPC server is experimental/insecure and must not be exposed to an open network.

The M1 harness therefore uses the smallest controlled surface needed to test the hypothesis:

- literal loopback/RFC1918 IPv4 RPC endpoints only;
- no DNS names and no `0.0.0.0` assisted bind;
- local coordinator HTTP listener forced to `127.0.0.1`;
- explicit device list and split ratios rather than implicit placement;
- `layer` split for shared RPC mode;
- `--fit off` so the requested split is not silently rewritten;
- `--offline` to prevent runtime-side model acquisition;
- one server slot;
- prompt cache disabled with `--cache-ram 0` and request `cache_prompt=false`;
- warmup disabled so the first measured request is explicit;
- no `--override-tensor` in the baseline because current upstream reports show placement coupling/failure risk around advanced overrides.

These choices are intentionally conservative and may change if the measured spike falsifies them.

## Entry point

```text
python -m runtime.llama.rpc_spike <command> ...
```

The caller supplies the actual current llama.cpp binaries. The harness does not download binaries or models and does not assume whether the upstream worker executable is named `rpc-server`, `ggml-rpc-server`, or something else.

## 1. Start the worker on a trusted private LAN

Example:

```bash
python -m runtime.llama.rpc_spike worker \
  --rpc-server /path/to/ggml-rpc-server \
  --bind 192.168.1.20 \
  --port 50052 \
  --devices CUDA0
```

The helper refuses public IPs, hostnames, IPv6 and wildcard binds. It deliberately does **not** enable the upstream RPC file cache or alter the host firewall.

## 2. Discover coordinator-visible devices

```bash
python -m runtime.llama.rpc_spike discover \
  --llama-server /path/to/llama-server \
  --rpc 192.168.1.20:50052
```

This runs current llama.cpp `--list-devices` with the RPC backend attached. Use the exact reported device names for the measured run; the harness does not guess backend ordering.

## 3. Create a local correctness/performance baseline

```bash
python -m runtime.llama.rpc_spike baseline \
  --llama-server /path/to/llama-server \
  --model /models/model.gguf \
  --devices CUDA0 \
  --output-dir artifacts/m1/local-baseline
```

The default probe is deterministic/greedy, disables prompt caching, and requests token IDs when the current server returns them.

## 4. Run the explicit local + RPC split

Example device names only — always use the names from `discover`:

```bash
python -m runtime.llama.rpc_spike run \
  --llama-server /path/to/llama-server \
  --model /models/model.gguf \
  --rpc 192.168.1.20:50052 \
  --devices 'CUDA0,RPC0[192.168.1.20:50052]' \
  --tensor-split 3,1 \
  --output-dir artifacts/m1/shared-rpc
```

The coordinator process is local-only at `127.0.0.1`; only the upstream RPC connection reaches the private worker.

## 5. Compare baseline and shared result

```bash
python -m runtime.llama.rpc_spike compare \
  --baseline artifacts/m1/local-baseline/runtime_spike_result.json \
  --shared artifacts/m1/shared-rpc/runtime_spike_result.json \
  --output artifacts/m1/comparison.json
```

Comparison requires the exact same model SHA-256 and prompt SHA-256. When both responses expose token IDs, correctness is compared by token-ID digest; otherwise it falls back to output-text digest. A mismatch returns a non-zero exit status.

The comparison also reports shared/baseline ratios for prefill tokens/s, decode tokens/s, and end-to-end request time. A successful match is evidence for that exact binary/model/topology only — not a general llama.cpp or ComputeMesh correctness claim.

## Evidence records

`runtime_spike_result.json` contains:

- full model SHA-256 and byte size;
- bounded llama.cpp `--version` output;
- private RPC topology;
- exact device names and split ratios;
- model-ready and request times;
- upstream prompt/decode timing metrics;
- SHA-256 of prompt/output/token IDs.

It does **not** persist raw prompts or raw outputs.

If a measured run fails after the output directory is created, the harness writes a bounded `runtime_spike_failure.json` with the phase, exception type and diagnostic text. It does not copy prompt/output content into that failure record.

The result schema is `spike_result.schema.json`.

## Tests

```bash
python -m unittest discover -s runtime/llama/tests -v
```

The initial harness adds 12 unit/schema/negative tests covering private endpoint restrictions, worker/coordinator command safety, explicit shared placement, local baseline, no-cache deterministic request settings, bounded response parsing, model hashing, failure-record privacy, baseline/shared comparison and result schema constraints.

## Important limitations

This code does **not** yet prove M1. In particular:

- no real private-LAN shared run has been recorded yet;
- no activation-byte accounting exists yet;
- no controlled latency/jitter/loss injection exists yet;
- no cancellation/disconnect experiment is recorded yet;
- no ComputeMesh scheduler chooses the split yet;
- no artifact preparation/verification wire path drives the runtime yet;
- upstream RPC provides no ComputeMesh authentication/security boundary.

ADR 0002 therefore remains `Proposed` until the real two-node spike satisfies its acceptance criteria or falsifies this runtime choice.

## Security boundary

Never expose the upstream RPC worker to the public internet or an untrusted network. The current ComputeMesh identity/session work does not authenticate this upstream RPC socket. A future production worker must place runtime-specific communication behind the authenticated/authorized ComputeMesh node boundary rather than treating RPC as the node API.
