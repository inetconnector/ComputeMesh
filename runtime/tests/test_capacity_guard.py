from datetime import UTC, datetime, timedelta
import threading
import time
import unittest

from runtime.capacity_guard import (
    CapacityExceededError,
    CapacityGuardError,
    InvalidLeaseError,
    LocalCapacityGuard,
)


class TestLocalCapacityGuard(unittest.TestCase):
    def setUp(self) -> None:
        self.guard = LocalCapacityGuard(
            node_id="node-test-1",
            max_concurrent_jobs=2,
            total_memory_mb=16384,
            default_ttl_seconds=5,
        )

    def test_initial_status(self) -> None:
        status = self.guard.get_status()
        self.assertEqual(status["node_id"], "node-test-1")
        self.assertEqual(status["active_jobs"], 0)
        self.assertEqual(status["max_concurrent_jobs"], 2)
        self.assertEqual(status["available_slots"], 2)
        self.assertEqual(status["used_memory_mb"], 0)
        self.assertEqual(status["total_memory_mb"], 16384)
        self.assertEqual(status["available_memory_mb"], 16384)

    def test_acquire_and_release(self) -> None:
        res = self.guard.acquire(job_id="job-1", memory_mb=4096, ttl_seconds=10)
        self.assertEqual(res.job_id, "job-1")
        self.assertEqual(res.node_id, "node-test-1")
        self.assertEqual(res.memory_mb, 4096)
        self.assertTrue(res.lease_id.startswith("local-lease-"))

        status = self.guard.get_status()
        self.assertEqual(status["active_jobs"], 1)
        self.assertEqual(status["available_slots"], 1)
        self.assertEqual(status["used_memory_mb"], 4096)
        self.assertEqual(status["available_memory_mb"], 12288)

        released = self.guard.release("job-1")
        self.assertTrue(released)
        self.assertEqual(self.guard.get_status()["active_jobs"], 0)

        # Releasing non-existent job returns False
        self.assertFalse(self.guard.release("job-non-existent"))

    def test_concurrency_limit_enforced(self) -> None:
        self.guard.acquire(job_id="job-1", memory_mb=2048)
        self.guard.acquire(job_id="job-2", memory_mb=2048)

        # 3rd job exceeds max_concurrent_jobs=2
        with self.assertRaises(CapacityExceededError) as ctx:
            self.guard.acquire(job_id="job-3", memory_mb=2048)
        self.assertIn("concurrent job limit reached", str(ctx.exception))

        # Releasing one allows acquisition again
        self.guard.release("job-1")
        res3 = self.guard.acquire(job_id="job-3", memory_mb=2048)
        self.assertEqual(res3.job_id, "job-3")

    def test_memory_limit_enforced(self) -> None:
        self.guard.acquire(job_id="job-1", memory_mb=12000)

        # Attempting to allocate 6000 MB when only 4384 MB remain
        with self.assertRaises(CapacityExceededError) as ctx:
            self.guard.acquire(job_id="job-2", memory_mb=6000)
        self.assertIn("insufficient local memory", str(ctx.exception))

    def test_duplicate_active_job_rejected(self) -> None:
        self.guard.acquire(job_id="job-1", memory_mb=2048)
        with self.assertRaises(CapacityExceededError) as ctx:
            self.guard.acquire(job_id="job-1", memory_mb=2048)
        self.assertIn("already holds an active reservation", str(ctx.exception))

    def test_ttl_expiry_and_pruning(self) -> None:
        # Acquire with 1 second TTL
        self.guard.acquire(job_id="job-short", memory_mb=4096, ttl_seconds=1)
        self.assertEqual(len(self.guard.get_active_reservations()), 1)

        time.sleep(1.1)
        # Should now be expired and pruned
        active = self.guard.get_active_reservations()
        self.assertEqual(len(active), 0)
        self.assertEqual(self.guard.get_status()["active_jobs"], 0)

    def test_renew_active_reservation(self) -> None:
        res = self.guard.acquire(job_id="job-1", memory_mb=2048, ttl_seconds=2)
        initial_expires = res.expires_at

        time.sleep(0.1)
        renewed = self.guard.renew("job-1", additional_seconds=10)
        self.assertEqual(renewed.job_id, "job-1")
        self.assertGreater(renewed.expires_at, initial_expires)

        # Renewing non-existent raises InvalidLeaseError
        with self.assertRaises(InvalidLeaseError):
            self.guard.renew("job-unknown", additional_seconds=10)

    def test_reserve_context_manager(self) -> None:
        with self.guard.reserve(job_id="job-ctx", memory_mb=4096) as res:
            self.assertEqual(res.job_id, "job-ctx")
            self.assertEqual(self.guard.get_status()["active_jobs"], 1)

        # Automatically released upon exiting context
        self.assertEqual(self.guard.get_status()["active_jobs"], 0)

    def test_reserve_context_manager_exception_safety(self) -> None:
        try:
            with self.guard.reserve(job_id="job-fail", memory_mb=4096):
                self.assertEqual(self.guard.get_status()["active_jobs"], 1)
                raise RuntimeError("simulated job failure")
        except RuntimeError:
            pass

        # Released even after unhandled exception
        self.assertEqual(self.guard.get_status()["active_jobs"], 0)

    def test_concurrent_thread_acquisitions(self) -> None:
        guard = LocalCapacityGuard(node_id="node-thread-test", max_concurrent_jobs=5)
        successes = []
        failures = []

        def worker(job_idx: int) -> None:
            try:
                with guard.reserve(job_id=f"job-{job_idx}", ttl_seconds=2):
                    time.sleep(0.05)
                    successes.append(job_idx)
            except CapacityGuardError:
                failures.append(job_idx)

        threads = [threading.Thread(target=worker, args=(i,)) for i in range(15)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        # Exactly 15 total attempts, at least 5 successes and some capacity-limited failures
        self.assertEqual(len(successes) + len(failures), 15)
        self.assertGreaterEqual(len(successes), 5)


if __name__ == "__main__":
    unittest.main()
