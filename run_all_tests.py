#!/usr/bin/env python3
"""ComputeMesh Unified Test Framework & Quality Assurance Test Runner.

Executes all unit, integration, financial ledger, security, and performance test suites
across the entire ComputeMesh repository with granular category reporting and benchmark metrics.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import sys
import time
import unittest

REPO_ROOT = Path(__file__).resolve().parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

# Test Suite Categories
CATEGORIES: dict[str, list[str]] = {
    "Gateway Subsystem": [
        "services.gateway.tests.test_gateway_server",
        "services.gateway.tests.test_gateway_auth",
        "services.gateway.tests.test_gateway_security",
        "services.gateway.tests.test_catalog_and_pricing",
        "services.gateway.tests.test_inference_engine",
        "services.gateway.tests.test_inference_backend",
        "services.gateway.tests.test_orchestrated_inference_backend",
        "services.gateway.tests.test_placement_selection",
    ],
    "Portal & Web Subsystem": [
        "services.portal.tests.test_portal_server",
        "services.portal.tests.test_portal_modular",
    ],
    "Billing & Financial Ledger": [
        "services.billing.tests.test_ledger",
        "services.billing.tests.test_stripe_integration",
        "services.billing.tests.test_accounting_and_settlement",
        "services.billing.tests.test_crypto_payments",
    ],
    "Identity & Vault Security": [
        "services.identity.tests.test_vault",
        "services.identity.tests.test_store",
        "services.identity.tests.test_integration",
    ],
    "Appliance & Hardware Daemon": [
        "tools.appliance.tests.test_appliance_config",
        "services.appliance_dashboard.tests.test_dashboard_server",
        "tools.appliance.tests.test_hardware_detector",
        "tools.appliance.tests.test_multi_gpu_launcher",
    ],
    "Scheduler & Orchestrator": [
        "services.scheduler.tests.test_placement",
        "services.scheduler.tests.test_health_monitor",
        "services.scheduler.tests.test_evidence_bundle",
        "services.scheduler.tests.test_multi_gpu_planner",
        "services.scheduler.tests.test_model_cache_manager",
        "services.orchestrator.tests.test_handlers",
        "services.orchestrator.tests.test_state_machine",
        "services.orchestrator.tests.test_persistence_v2",
    ],
    "Runtime & Mesh Network": [
        "runtime.network.tests.test_tcp_relay",
        "runtime.network.tests.test_mesh_transport",
        "runtime.llama.tests.test_shared_trial",
        "runtime.llama.tests.test_shared_run_evidence",
        "runtime.llama.tests.test_rpc_spike",
    ],
    "Configuration & Performance": [
        "services.common.tests.test_config",
        "tools.benchmark.tests.test_performance_harness",
        "tools.benchmark.tests.test_gguf_manifest",
        "tools.benchmark.tests.test_network_benchmark",
        "tools.benchmark.tests.test_llama_bench_adapter",
        "services.updater.tests.test_auto_updater",
    ],
}


@dataclass
class CategoryResult:
    name: str
    total: int
    passed: int
    failed: int
    errors: int
    duration_sec: float


def run_test_suite() -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

    print("=" * 80)
    print(" [COMPUTEMESH] UNIFIED TEST SUITE & QUALITY ASSURANCE HARNESS")
    print("=" * 80)

    loader = unittest.TestLoader()
    overall_start = time.perf_counter()
    category_results: list[CategoryResult] = []
    all_successful = True

    for cat_name, modules in CATEGORIES.items():
        print(f"\n>> Running Category: {cat_name}...")
        suite = unittest.TestSuite()
        for mod in modules:
            try:
                tests = loader.loadTestsFromName(mod)
                suite.addTests(tests)
            except Exception as exc:
                print(f"  [ERROR] Failed to load test module {mod}: {exc}")
                all_successful = False

        cat_start = time.perf_counter()
        runner = unittest.TextTestRunner(verbosity=1)
        result = runner.run(suite)
        cat_duration = time.perf_counter() - cat_start

        failures_count = len(result.failures)
        errors_count = len(result.errors)
        passed_count = result.testsRun - (failures_count + errors_count)

        if not result.wasSuccessful():
            all_successful = False

        category_results.append(CategoryResult(
            name=cat_name,
            total=result.testsRun,
            passed=passed_count,
            failed=failures_count,
            errors=errors_count,
            duration_sec=cat_duration,
        ))

    total_duration = time.perf_counter() - overall_start

    print("\n" + "=" * 80)
    print(" TEST EXECUTION SUMMARY")
    print("=" * 80)
    print(f"{'Category':<32} | {'Total':<6} | {'Passed':<7} | {'Failed':<6} | {'Errors':<6} | {'Time (s)':<8}")
    print("-" * 80)

    total_all = sum(r.total for r in category_results)
    passed_all = sum(r.passed for r in category_results)
    failed_all = sum(r.failed for r in category_results)
    errors_all = sum(r.errors for r in category_results)

    for r in category_results:
        status_flag = "[OK]  " if r.failed == 0 and r.errors == 0 else "[FAIL]"
        print(f"{status_flag} {r.name:<25} | {r.total:<6} | {r.passed:<7} | {r.failed:<6} | {r.errors:<6} | {r.duration_sec:<8.2f}")

    print("-" * 80)
    summary_flag = "ALL TESTS PASSED" if all_successful else "FAILURES DETECTED"
    print(f"Total Across All Subsystems     | {total_all:<6} | {passed_all:<7} | {failed_all:<6} | {errors_all:<6} | {total_duration:<8.2f}")
    print(f"\nFinal Result: {summary_flag} ({passed_all}/{total_all} tests passing in {total_duration:.2f}s)\n")

    return 0 if all_successful else 1


if __name__ == "__main__":
    sys.exit(run_test_suite())
