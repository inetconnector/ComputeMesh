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

CATEGORIES: dict[str, list[str]] = {
    "Protocol & Session Wire": [
        "protocol.tests.test_attestation_session_wire",
    ],
    "Gateway Subsystem": [
        "services.gateway.tests.test_gateway_server",
        "services.gateway.tests.test_gateway_auth",
        "services.gateway.tests.test_gateway_security",
        "services.gateway.tests.test_catalog_and_pricing",
        "services.gateway.tests.test_inference_engine",
        "services.gateway.tests.test_inference_backend",
        "services.gateway.tests.test_orchestrated_inference_backend",
        "services.gateway.tests.test_placement_selection",
        "services.gateway.tests.test_execution_evidence",
        "services.gateway.tests.test_verified_settlement",
        "services.gateway.tests.test_cancellable_inference",
        "services.gateway.tests.test_owner_promo_routes",
        "services.gateway.tests.test_server_driven_gpu_promo",
        "tests.test_security_audit_fixes",
        "tests.test_gateway_passkey_auth",
    ],
    "Portal & Web Subsystem": [
        "services.portal.tests.test_portal_server",
        "services.portal.tests.test_portal_modular",
        "services.portal.tests.test_fleet_accounts",
        "services.portal.tests.test_passkey_routes",
        "services.portal.tests.test_fleet_http",
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
        "tools.security.tests.test_node_key_storage",
    ],
    "Appliance & Hardware Daemon": [
        "tools.appliance.tests.test_appliance_config",
        "services.appliance_dashboard.tests.test_dashboard_server",
        "tools.appliance.tests.test_hardware_detector",
        "tools.appliance.tests.test_multi_gpu_launcher",
        "tools.appliance.tests.test_disk_clone",
        "apps.node.test_provider_agent",
    ],
    "Scheduler & Orchestrator": [
        "services.scheduler.tests.test_placement",
        "services.scheduler.tests.test_health_monitor",
        "services.scheduler.tests.test_evidence_bundle",
        "services.scheduler.tests.test_multi_gpu_planner",
        "services.scheduler.tests.test_model_cache_manager",
        "services.orchestrator.tests.test_handlers",
        "services.orchestrator.tests.test_state_machine",
        "services.orchestrator.tests.test_persistence",
        "services.orchestrator.tests.test_persistence_v2",
        "services.orchestrator.tests.test_attestation_collection",
        "services.orchestrator.tests.test_authenticated_attestation_transport",
        "services.orchestrator.tests.test_authenticated_gpu_promo_transport",
        "services.orchestrator.tests.test_gpu_promo_dispatch",
        "services.orchestrator.tests.test_shared_request_backend",
        "services.orchestrator.tests.test_shared_request_cancellation",
        "services.orchestrator.tests.test_live_shared_runtime",
        "services.orchestrator.tests.test_live_model_catalog",
        "services.orchestrator.tests.test_live_shared_recovery",
        "services.orchestrator.tests.test_live_request_cancel_registry",
        "services.orchestrator.tests.test_persistent_control_channel",
        "services.orchestrator.tests.test_live_provider_registration",
        "services.orchestrator.tests.test_startup_recovery",
        "services.orchestrator.tests.test_settlement_recovery",
        "services.orchestrator.tests.test_threaded_live_sqlite",
        "services.orchestrator.tests.test_billing_outbox",
        "services.orchestrator.tests.test_contracts",
        "services.orchestrator.tests.test_adversarial_fault_injection",
    ],
    "Runtime & Mesh Network": [
        "runtime.network.tests.test_tcp_relay",
        "runtime.network.tests.test_mesh_transport",
        "runtime.tests.test_capacity_guard",
        "runtime.llama.tests.test_shared_trial",
        "runtime.llama.tests.test_shared_run_evidence",
        "runtime.llama.tests.test_rpc_spike",
        "runtime.llama.tests.test_job_attestation",
        "runtime.llama.tests.test_job_bound_shared_trial",
        "runtime.llama.tests.test_shared_request",
        "runtime.llama.tests.test_shared_request_live_health",
    ],
    "Configuration & Performance": [
        "services.common.tests.test_config",
        "tools.benchmark.tests.test_performance_harness",
        "tools.benchmark.tests.test_gguf_manifest",
        "tools.benchmark.tests.test_network_benchmark",
        "tools.benchmark.tests.test_llama_bench_adapter",
        "services.updater.tests.test_auto_updater",
    ],
    "Confidential & Protected Execution": [
        "apps.client.tests.test_openai_proxy",
        "apps.client.tests.test_confidential_openai",
        "apps.client.tests.test_confidential_openai_stream",
        "runtime.confidential.tests.test_data_plane",
        "runtime.confidential.tests.test_protected_worker",
        "runtime.confidential.tests.test_protected_worker_lifecycle",
        "runtime.confidential.tests.test_protected_context",
        "runtime.confidential.tests.test_replay_store",
        "runtime.confidential.tests.test_session",
        "services.gateway.tests.test_confidential_live_bootstrap",
        "services.gateway.tests.test_confidential_coordinator",
        "services.gateway.tests.test_live_confidential_transport",
        "services.gateway.tests.test_live_confidential_gate",
        "services.gateway.tests.test_unified_live_protected_handler",
        "services.orchestrator.tests.test_remote_confidential_broker",
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
                suite.addTests(loader.loadTestsFromName(mod))
            except Exception as exc:
                print(f"  [ERROR] Failed to load test module {mod}: {exc}")
                all_successful = False
        cat_start = time.perf_counter()
        result = unittest.TextTestRunner(verbosity=1).run(suite)
        failures_count = len(result.failures)
        errors_count = len(result.errors)
        passed_count = result.testsRun - failures_count - errors_count
        if not result.wasSuccessful():
            all_successful = False
        category_results.append(CategoryResult(cat_name, result.testsRun, passed_count, failures_count, errors_count, time.perf_counter() - cat_start))
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
