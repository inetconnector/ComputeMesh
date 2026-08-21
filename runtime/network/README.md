# Runtime Network Measurement Relay

**Status:** M1 lab measurement instrument implemented; not a ComputeMesh production transport.

## Purpose

`runtime/network/tcp_relay.py` is a deliberately narrow TCP relay for measuring the current llama.cpp RPC experiment without exposing a new public protocol surface.

It exists to answer three immediate M1 questions:

1. how many TCP-stream bytes move in each direction during the shared-runtime experiment;
2. how the exact experiment behaves under reproducible added latency/jitter;
3. whether disconnect/failure behavior is observable and bounded.

It does **not** parse llama.cpp RPC frames and never stores payload bytes.

## Security boundary

The relay is intentionally more restrictive than a general TCP proxy:

- the listener is hard-coded to `127.0.0.1`;
- the target must be a literal IPv4 address;
- targets are limited to loopback or RFC1918 private ranges;
- DNS names, IPv6, wildcard binds, link-local and public addresses are rejected;
- no inbound public listener is created;
- no payload inspection or payload logging exists;
- operational socket errors are reduced to bounded exception type / `errno` evidence.

This does **not** make upstream llama.cpp RPC authenticated or safe for untrusted networks. The real RPC worker still belongs only on a trusted private lab network.

## Backpressure and resource bounds

Each relay direction uses a bounded queue. `--chunk-bytes` defaults to 64 KiB and `--max-buffer-bytes` defaults to 8 MiB. Configuration is bounded to:

- chunk: 1 KiB .. 1 MiB;
- configured queue budget: one chunk .. 256 MiB;
- added one-way delay: 0 .. 60 s;
- jitter amplitude: 0 .. 60 s;
- worker connect timeout: >0 .. 120 s.

The queue capacity is derived from `max_buffer_bytes // chunk_bytes`; current in-flight socket/runtime buffers remain outside that userspace queue budget.

## Normal measurement flow

Assume the real llama.cpp RPC worker is running on `192.168.1.20:50052`.

Start the relay on the coordinator machine:

```bash
python -m runtime.network.tcp_relay \
  --target 192.168.1.20:50052 \
  --listen-port 50053 \
  --metrics artifacts/m1/relay/relay.json
```

It prints:

```text
READY 127.0.0.1:50053 -> 192.168.1.20:50052
```

Then point the llama.cpp experiment at the local relay rather than directly at the remote worker:

```bash
python -m runtime.llama.rpc_spike discover \
  --llama-server /path/to/llama-server \
  --rpc 127.0.0.1:50053
```

For the measured shared run, use the exact RPC device name reported by that discovery step and the same relay endpoint in `--rpc`.

The relay is one-shot: it accepts one coordinator TCP connection, forwards that connection to the configured private worker, writes its metrics, and exits.

## Added latency and jitter

Example: add approximately 12 ms one-way userspace forwarding delay with deterministic ±2 ms chunk jitter:

```bash
python -m runtime.network.tcp_relay \
  --target 192.168.1.20:50052 \
  --listen-port 50053 \
  --delay-ms 12 \
  --jitter-ms 2 \
  --seed 42 \
  --metrics artifacts/m1/relay/delay-12-jitter-2.json
```

This models delayed **TCP stream-chunk forwarding**, not physical packet latency. It is useful for controlled sensitivity experiments but must not be described as packet-level network emulation.

## Controlled disconnects

Force the relay connection down after an active connected duration:

```bash
python -m runtime.network.tcp_relay \
  --target 192.168.1.20:50052 \
  --disconnect-after-seconds 2.0 \
  --metrics artifacts/m1/relay/disconnect-time.json
```

Or after at least a total number of successfully forwarded stream bytes across both directions:

```bash
python -m runtime.network.tcp_relay \
  --target 192.168.1.20:50052 \
  --disconnect-after-bytes 1048576 \
  --metrics artifacts/m1/relay/disconnect-bytes.json
```

The byte threshold can overshoot by up to an in-flight relay chunk because counting occurs after a successful `sendall`.

## Timing semantics

Relay metrics deliberately separate operator/setup delay from the active connection:

- `setup_elapsed_ms`: relay start until both coordinator and worker are connected; this includes time waiting for the coordinator;
- `active_elapsed_ms`: both sides connected until termination;
- `total_elapsed_ms`: full one-shot relay lifetime.

A worker connection failure has `connected_at = null` and `active_elapsed_ms = 0` and is still persisted as `connect_error` evidence.

## Metrics

`relay_metrics.schema.json` constrains the content-free record. It includes:

- listener and private target endpoint;
- requested delay/jitter/buffer/fault configuration;
- setup, active and total timing;
- coordinator → worker bytes;
- worker → coordinator bytes;
- total forwarded bytes;
- termination reason and bounded operational error metadata.

It contains no field for payload, prompt, model output or arbitrary captured stream content.

## What this does not measure

The current relay does **not** claim to measure activation tensors or RPC message classes. It sees only an opaque TCP byte stream, so the byte counts include all llama.cpp RPC framing/control/data traffic.

It also deliberately does **not** simulate packet loss by dropping TCP stream bytes. Removing bytes inside a reliable TCP byte stream would corrupt the application protocol, not emulate IP packet loss/retransmission. Real loss/reordering experiments require an OS/network layer such as Linux `tc netem`, an equivalent controlled network emulator, or a dedicated transport testbed.

## Tests

```bash
python -m unittest discover -s runtime/network/tests -v
```

Coverage includes:

- public/DNS/IPv6/wildcard/link-local rejection;
- configuration/resource bounds;
- real loopback full-duplex forwarding and exact byte accounting;
- delayed forwarding;
- setup-vs-active timing separation;
- byte-triggered disconnect;
- time-triggered disconnect beginning only after both endpoints connect;
- worker-connect failure evidence;
- content-free metrics schema constraints.

The user-facing `SETUP.cmd` / `./setup.sh` **all tests** path also runs this suite.

## M1 evidence boundary

The relay is now available to instrument the first real two-machine llama.cpp RPC run. No real shared-runtime byte totals, injected-delay results, disconnect results, or packet-loss results have been recorded yet.
