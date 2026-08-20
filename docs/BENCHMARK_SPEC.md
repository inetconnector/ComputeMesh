# ComputeMesh Benchmark Specification

**Status:** Draft v0.1  
**Purpose:** create scheduler-grade, reproducible measurements rather than marketing benchmarks.

## 1. Principles

A benchmark result is valid only with its context.

Every result MUST include:

- benchmark schema version;
- run ID;
- node/device/profile revision;
- OS and kernel/build;
- driver/runtime versions;
- model and quantization where applicable;
- benchmark parameters;
- warm/cold state;
- power/thermal condition;
- timestamp;
- sample count;
- raw measurements or reference to raw artifact.

The scheduler should use recent observed performance with uncertainty, not a static GPU-name lookup table.

## 2. Hardware inventory

Capture:

- CPU model, cores/threads;
- RAM total/available;
- GPU vendor/model/device ID;
- VRAM total/available;
- compute capability/backend features;
- driver;
- runtime/backend;
- storage type/free space;
- network interfaces;
- OS version;
- power/thermal telemetry availability.

Do not collect unnecessary hardware identifiers that create privacy risk.

## 3. Device microbenchmarks

### Memory

- host memory bandwidth;
- device memory bandwidth;
- host-to-device;
- device-to-host;
- peer transfer where supported.

### Compute

- FP16/BF16 GEMM;
- relevant low-precision/quantized GEMM;
- matrix sizes representative of target models;
- warm-up followed by timed samples.

Report:

- throughput;
- median;
- p95;
- variance;
- temperature/power if available.

## 4. Model-operation benchmarks

### Prefill

Variables:

- model;
- quantization;
- batch;
- prompt lengths;
- context length.

Metrics:

- tokens/s;
- wall time;
- GPU utilization;
- peak memory.

### Decode

Variables:

- active sequences;
- context lengths;
- generated token count.

Metrics:

- inter-token latency distribution;
- decode tokens/s;
- memory growth;
- utilization.

### KV cache

Measure:

- bytes per token;
- allocation rate;
- maximum tested context;
- migration throughput if runtime supports it.

## 5. Network benchmark

For each relevant peer/path:

- RTT p50/p95/p99;
- jitter;
- application throughput;
- packet loss if measurable;
- connection setup;
- small-frame latency;
- large-frame throughput;
- concurrent stream behavior.

Use application-level transfer tests in addition to generic network tools.

## 6. Activation transport benchmark

Measure tensors representative of stage boundaries.

Variables:

- payload size;
- dtype;
- compression/quantization if used;
- number of in-flight frames;
- RTT;
- bandwidth;
- jitter/loss.

Metrics:

- encode time;
- queue time;
- wire time;
- decode time;
- effective throughput;
- end-to-end stage-transfer latency.

## 7. Artifact preparation

Measure cold and warm cases:

- download;
- digest verification;
- cache hit;
- map/load;
- runtime initialization;
- first usable stage.

Report model-ready time separately from inference TTFT.

## 8. Failure benchmarks

Inject:

- process termination;
- network disconnect;
- latency spike;
- packet loss;
- GPU OOM;
- GPU reset where safe;
- corrupted artifact;
- stale reservation;
- duplicate command.

Measure:

- detection time;
- user-visible interruption;
- recovery/replan;
- lost work;
- billing effect.

## 9. Statistical rules

Minimum M0 guidance:

- warm-up before steady-state runs;
- at least 10 samples for latency microbenchmarks where practical;
- report median and p95, not only mean;
- retain raw samples;
- flag thermal throttling;
- distinguish cold/warm cache;
- do not combine prefill and decode into one unlabeled tokens/s number.

## 10. Profile freshness

Results degrade with:

- competing local workloads;
- thermal state;
- driver/runtime update;
- network changes;
- power limits.

The scheduler should attach:

- sample age;
- confidence;
- observed prediction error.

Critical benchmark families are rerun on material hardware/runtime changes.

## 11. Gate 1 benchmark record

A G1 evidence bundle should include:

- both node profiles;
- runtime/model manifests;
- placement plan;
- reservation trace;
- raw benchmark IDs;
- inference metrics;
- correctness check;
- network conditions;
- failure test;
- exact reproduction command.
