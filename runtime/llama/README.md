# llama.cpp Runtime Integration

**Status:** M1 research spike harness and fail-closed shared-run evidence binding implemented; no real distributed-inference result yet.

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

Direct connection:

```bash
python -m runtime.llama.rpc_spike discover \
  --llama-server /path/to/llama-server \
  --rpc 192.168.1.20:50052
```

For instrumented experiments, start `runtime.network.tcp_relay` locally and use its loopback endpoint instead:

```bash
python -m runtime.network.tcp_relay \
  --target 192.168.1.20:50052 \
  --listen-port 50053 \
  --metrics artifacts/m1/relay/discover.json
```

Then:

```bash
python -m runtime.llama.rpc_spike discover \
  --llama-server /path/to/llama-server \
  --rpc 127.0.0.1:50053
```

The discovery step reports the exact local/RPC device names from the current llama.cpp build. The relay is one-shot, so start a fresh relay for the measured shared run.

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

Example device names only — always use the names from `discover` and the exact split selected by the current experiment bundle/planner:

```bash
python -m runtime.llama.rpc_spike run \
  --llama-server /path/to/llama-server \
  --model /models/model.gguf \
  --rpc 192.168.1.20:50052 \
  --devices 'CUDA0,RPC0[192.168.1.20:50052]' \
  --tensor-split 3,1 \
  --output-dir artifacts/m1/shared-rpc
```

For the first measured proof, start a fresh zero-delay measurement relay and use its loopback endpoint in both the `--rpc` value and the exact RPC device name returned by discovery for that relayed topology.

The coordinator HTTP process remains local-only at `127.0.0.1`; only the upstream RPC connection traverses the trusted private network.

## 5. Compare baseline and shared result

```bash
python -m runtime.llama.rpc_spike compare \
  --baseline artifacts/m1/local-baseline/runtime_spike_result.json \
  --shared artifacts/m1/shared-rpc/runtime_spike_result.json \
  --output artifacts/m1/comparison.json
```

Comparison requires the exact same model SHA-256 and prompt SHA-256. When both responses expose token IDs, correctness is compared by token-ID digest; otherwise it falls back to output-text digest. A mismatch returns a non-zero exit status.

The comparison also reports shared/baseline ratios for prefill tokens/s, decode tokens/s, and end-to-end request time. A successful match is evidence for that exact binary/model/topology only — not a general llama.cpp or ComputeMesh correctness claim.

## 6. Bind the first shared-run proof

After a current `experiment_bundle.json`, local baseline, relayed shared run and relay metrics exist, build one fail-closed proof artifact:

```bash
python -m runtime.llama.shared_run_evidence \
  --bundle artifacts/m1/experiment_bundle.json \
  --baseline artifacts/m1/local-baseline/runtime_spike_result.json \
  --shared artifacts/m1/shared-rpc/runtime_spike_result.json \
  --relay artifacts/m1/relay/shared-run.json \
  --output artifacts/m1/shared_run_evidence.json
```

`shared_run_evidence.py` validates all source documents against their repository schemas and then requires the evidence to describe one coherent first proof:

- the bundle must recommend `shared_experiment` and contain one feasible two-node contiguous-layer candidate;
- baseline and shared run must use the bundle's exact model basename, byte size and SHA-256;
- both runs must use the same bounded llama.cpp version string and prompt digest;
- the baseline must use one local coordinator device;
- the first shared device must be that same coordinator device and the second must be the RPC device;
- the shared `tensor_split` must exactly match the planner-selected coordinator/worker order;
- the shared run must use exactly the relay's loopback listen endpoint, while the relay target must itself be loopback/RFC1918;
- the first proof must have zero configured relay delay/jitter, no forced disconnect, an actual connection ending by EOF, and positive byte flow in both directions;
- timestamps must form a bounded `bundle -> baseline -> relay/shared` chain rather than combining unrelated historical runs;
- token-ID digests must match when both are available, otherwise output-text digests must match exactly.

The output binds every input file by basename and SHA-256 and records model/runtime identity, planner split, correctness digests, request/token timing ratios, relay timing and opaque directional byte totals. It deliberately contains no raw prompt or raw output, refuses symlinked/oversized/non-finite input JSON, and will not overwrite an existing proof path.

The proof ID is content-derived from the source document hashes and comparison result; its observational `captured_at` is not the evidence identity.

This helper **does not execute the experiment**, authenticate the worker, prove the relay target's physical identity, identify activation tensors, or authorize production scheduling. `production_scheduling` is always `false`.

The result schema is `shared_run_evidence.schema.json`.

## Network instrumentation

`runtime/network/tcp_relay.py` is a separate lab instrument, not part of the llama runtime protocol. It can:

- count opaque TCP-stream bytes in both directions;
- separate setup/wait time from active connected relay time;
- add deterministic userspace one-way delay and chunk jitter;
- force a disconnect after active time or total forwarded bytes;
- persist content-free failure/termination evidence.

It does not parse RPC frames, so byte counts include all RPC framing/control/data traffic and are **not** activation-tensor byte counts.

It also does not emulate packet loss. Dropping arbitrary bytes from a reliable TCP stream would corrupt the protocol rather than model IP loss/retransmission. Packet-level loss/reordering remains a later OS/network-emulation experiment.

See [../network/README.md](../network/README.md).

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

The runtime result schema is `spike_result.schema.json`; the bound proof schema is `shared_run_evidence.schema.json`.

## Tests

```bash
python -m unittest discover -s runtime/llama/tests -v
python -m unittest discover -s runtime/network/tests -v
```

The llama runtime suite covers private endpoint restrictions, worker/coordinator command safety, explicit shared placement, local baseline, no-cache deterministic request settings, bounded response parsing, model hashing, failure-record privacy, baseline/shared comparison, result schemas, planner split/device-order binding, proof chronology, relay-path binding, relay byte consistency, unperturbed-first-proof constraints, non-finite input rejection and output privacy.

The network relay has its own real-loopback forwarding/fault/timing/schema tests and is also included in the full cross-platform validation path.

## Important limitations

This code does **not** yet prove M1. In particular:

- no real private-LAN shared run has been recorded yet;
- opaque RPC byte accounting exists, but activation tensors are not identified separately;
- controlled TCP-stream delay/jitter injection exists, but no packet-level loss/reordering result exists;
- controlled relay disconnect injection exists, but no real llama.cpp disconnect experiment has been recorded yet;
- the current planner can select the experimental split, but it is a conservative feasibility planner and not a calibrated production scheduler;
- the proof builder validates already-created artifacts; it does not drive llama.cpp or the relay;
- no artifact preparation/verification wire path drives the runtime yet;
- upstream RPC provides no ComputeMesh authentication/security boundary.

ADR 0002 therefore remains `Proposed` until the real two-node spike satisfies its acceptance criteria or falsifies this runtime choice.

## Security boundary

Never expose the upstream RPC worker to the public internet or an untrusted network. The current ComputeMesh identity/session work does not authenticate this upstream RPC socket. A future production worker must place runtime-specific communication behind the authenticated/authorized ComputeMesh node boundary rather than treating RPC as the node API.
