# ComputeMesh Test Suite & Quality Assurance Matrix

## Overview
The ComputeMesh QA & Verification Framework is orchestrated via [`run_all_tests.py`](file:///c:/Users/frede/Projekte/ComputeMesh/run_all_tests.py), providing unified discovery, categorized test execution, benchmark latency tracking, and concurrency stress testing across all system layers.

---

## Test Categories & Coverage Matrix

| Subsystem Category | Test Modules | Total Tests | Status | Avg Execution Time |
| :--- | :--- | :--- | :--- | :--- |
| **Protocol & Session Wire** | protocol contract and session-wire tests | **3** | `[OK]` | ~0.01s |
| **Gateway Subsystem** | `test_gateway_server`, `test_gateway_auth`, `test_gateway_security`, `test_catalog_and_pricing`, `test_inference_engine`, runtime-backend coverage | **69** | `[OK]` | ~1.07s |
| **Portal & Web Subsystem** | `test_portal_server`, `test_portal_modular` | **13** | `[OK]` | ~0.70s |
| **Billing & Financial Ledger** | `test_ledger`, `test_stripe_integration`, `test_accounting_and_settlement`, `test_crypto_payments`, durable billing outbox recovery | **35** | `[OK]` | ~0.38s |
| **Identity & Vault Security** | `test_vault`, `test_store`, `test_integration` | **17** | `[OK]` | ~0.16s |
| **Appliance & Hardware Daemon**| `test_appliance_config`, `test_dashboard_server`, `test_hardware_detector`, `test_multi_gpu_launcher` | **10** | `[OK]` | ~3.07s |
| **Scheduler & Orchestrator** | placement/evidence bundle, live shared request orchestration, recovery, cancellation, attestation, persistence and control-plane tests | **108** | `[OK]` | ~1.23s |
| **Runtime & Mesh Network** | `test_tcp_relay`, `test_mesh_transport`, `test_shared_trial`, `test_shared_run_evidence`, `test_rpc_spike`, live shared-runtime support | **66** | `[OK]` | ~5.10s |
| **Configuration & Performance** | `test_config`, `test_performance_harness`, `test_gguf_manifest`, `test_network_benchmark`, `test_llama_bench_adapter`, `test_auto_updater` | **36** | `[OK]` | ~0.24s |
| **TOTAL** | **All 9 Subsystems** | **357** | `[ALL PASS]` | **12.32s** |

---

## Benchmark & Performance Metrics (Prämisse 1)

### Single-Threaded Inference Dispatch Latency
- **Average Dispatch Latency:** `0.048 ms` per request (synthetic gateway dispatch overhead)
- **Token Estimation & Ledger Recording:** `< 0.020 ms`
- **Memory Footprint & Cleanup:** Sockets cleanly terminated with `Connection: close` and `self.close_connection = True`.

### Multi-Threaded Concurrency Stress Test
- **Workers:** 16 Concurrent OS Threads
- **Throughput:** `29,023.7 requests/second`
- **Double-Entry Financial Ledger Invariant:** 100% debit/credit balancing under heavy contention with `threading.RLock()`.

---

## Running the Test Suite

```bash
# Central runner for all tests
python run_all_tests.py

# Run specific subsystem tests
python -m unittest services.gateway.tests.test_gateway_auth -v
python -m unittest services.gateway.tests.test_inference_engine -v
python -m unittest tools.benchmark.tests.test_performance_harness -v
```

Latest local validation: `python run_all_tests.py` passed 357/357 tests in 12.32s on 2026-08-26.
