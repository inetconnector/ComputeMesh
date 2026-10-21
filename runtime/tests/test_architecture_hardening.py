"""Unit tests for Architecture Hardening & Fault Tolerance Engine."""
from __future__ import annotations

import time
import unittest

from runtime.architecture_hardening import (
    MeshCircuitBreaker,
    IdempotencyEnforcer,
    WorkloadAdmissionGate,
    CircuitBreakerOpenError,
    IdempotencyViolationError,
    WorkloadAdmissionError,
)

class TestMeshCircuitBreaker(unittest.TestCase):
    def setUp(self) -> None:
        self.breaker = MeshCircuitBreaker(failure_threshold=3, recovery_timeout_sec=0.1)

    def test_successful_execution(self) -> None:
        result = self.breaker.execute(lambda: "success")
        self.assertEqual(result, "success")
        self.assertEqual(self.breaker.state, "CLOSED")

    def test_circuit_opens_on_threshold_and_recovers(self) -> None:
        def failing_func():
            raise ValueError("Failure")

        # Fail 3 times
        for _ in range(3):
            with self.assertRaises(ValueError):
                self.breaker.execute(failing_func)

        # Circuit should now be OPEN
        self.assertEqual(self.breaker.state, "OPEN")

        # Further calls should raise CircuitBreakerOpenError immediately
        with self.assertRaises(CircuitBreakerOpenError):
            self.breaker.execute(lambda: "success")

        # Wait for recovery timeout
        time.sleep(0.2)

        # The first call after timeout should be in HALF_OPEN state
        # If it succeeds, circuit closes
        result = self.breaker.execute(lambda: "success")
        self.assertEqual(result, "success")
        self.assertEqual(self.breaker.state, "CLOSED")

    def test_half_open_failure_reopens_circuit(self) -> None:
        def failing_func():
            raise ValueError("Failure")

        # Open the circuit
        for _ in range(3):
            with self.assertRaises(ValueError):
                self.breaker.execute(failing_func)

        # Wait for recovery
        time.sleep(0.2)

        # Fail during HALF_OPEN
        with self.assertRaises(ValueError):
            self.breaker.execute(failing_func)

        # Circuit should be back to OPEN
        self.assertEqual(self.breaker.state, "OPEN")


class TestIdempotencyEnforcer(unittest.TestCase):
    def setUp(self) -> None:
        self.enforcer = IdempotencyEnforcer(ttl_sec=0.1)

    def test_execute_first_time(self) -> None:
        call_count = 0
        def func():
            nonlocal call_count
            call_count += 1
            return "computed"

        res = self.enforcer.check_and_record("key_1", func)
        self.assertEqual(res, "computed")
        self.assertEqual(call_count, 1)

    def test_idempotent_result(self) -> None:
        call_count = 0
        def func():
            nonlocal call_count
            call_count += 1
            return "computed"

        self.enforcer.check_and_record("key_1", func)

        # Second call should not increment call_count
        res = self.enforcer.check_and_record("key_1", func)
        self.assertEqual(res, "computed")
        self.assertEqual(call_count, 1)

    def test_empty_key_rejected(self) -> None:
        with self.assertRaises(IdempotencyViolationError):
            self.enforcer.check_and_record("", lambda: "val")

    def test_ttl_expiry(self) -> None:
        call_count = 0
        def func():
            nonlocal call_count
            call_count += 1
            return "computed"

        self.enforcer.check_and_record("key_1", func)

        # Wait for TTL
        time.sleep(0.2)

        # Key should be pruned, func executed again
        res = self.enforcer.check_and_record("key_1", func)
        self.assertEqual(res, "computed")
        self.assertEqual(call_count, 2)


class TestWorkloadAdmissionGate(unittest.TestCase):
    def setUp(self) -> None:
        self.gate = WorkloadAdmissionGate(
            allowed_models={"qwen2.5:7b", "llama3:8b"},
            max_memory_bytes=8_000_000_000  # 8 GB
        )

    def test_successful_lease_and_admission(self) -> None:
        self.gate.register_lease("lease_1", "qwen2.5:7b", 4_000_000_000)

        # Should admit workload
        self.assertTrue(self.gate.admit_workload("lease_1", "qwen2.5:7b"))

        # Cleanup
        self.gate.release_lease("lease_1")
        with self.assertRaises(WorkloadAdmissionError):
            self.gate.admit_workload("lease_1", "qwen2.5:7b")

    def test_unsupported_model_rejected(self) -> None:
        with self.assertRaises(WorkloadAdmissionError) as cm:
            self.gate.register_lease("lease_2", "unsupported-model", 1_000)
        self.assertIn("not supported", str(cm.exception))

    def test_memory_limit_exceeded(self) -> None:
        with self.assertRaises(WorkloadAdmissionError) as cm:
            self.gate.register_lease("lease_3", "qwen2.5:7b", 10_000_000_000) # 10 GB
        self.assertIn("bytes available", str(cm.exception))

    def test_duplicate_lease_id_rejected(self) -> None:
        self.gate.register_lease("lease_4", "qwen2.5:7b", 1_000)
        with self.assertRaises(WorkloadAdmissionError):
            self.gate.register_lease("lease_4", "qwen2.5:7b", 1_000)

    def test_unadmitted_workload_rejected(self) -> None:
        with self.assertRaises(WorkloadAdmissionError) as cm:
            self.gate.admit_workload("unknown_lease", "qwen2.5:7b")
        self.assertIn("No valid lease found", str(cm.exception))

    def test_lease_model_mismatch(self) -> None:
        self.gate.register_lease("lease_5", "qwen2.5:7b", 1_000)
        with self.assertRaises(WorkloadAdmissionError) as cm:
            self.gate.admit_workload("lease_5", "llama3:8b")
        self.assertIn("Lease model mismatch", str(cm.exception))

if __name__ == "__main__":
    unittest.main()
