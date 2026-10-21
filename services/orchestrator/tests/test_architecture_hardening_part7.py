import sqlite3
import time
import unittest
from services.orchestrator.architecture_hardening_part7 import (
    StatefulIdempotentCommandEnforcer,
    StatefulCapacityLeaseManager,
    StatefulIdempotencyError,
    StatefulCapacityLeaseError
)

class TestArchitectureHardeningPart7(unittest.TestCase):
    def setUp(self):
        self.db = sqlite3.connect(":memory:", isolation_level=None)

    def tearDown(self):
        self.db.close()

    def test_idempotent_command_enforcer(self):
        enforcer = StatefulIdempotentCommandEnforcer(self.db)

        # Valid: Read-only command
        res1 = enforcer.execute_command({"type": "read", "is_state_changing": False}, lambda: {"status": "executed_real"})
        self.assertEqual(res1["status"], "executed_real")

        # Valid: State-changing but idempotent by design
        res2 = enforcer.execute_command({"type": "set_flag", "is_state_changing": True, "is_idempotent_by_design": True}, lambda: {"status": "executed_real_2"})
        self.assertEqual(res2["status"], "executed_real_2")

        # Valid: State-changing with idempotency key
        counter = [0]
        def execute_action():
            counter[0] += 1
            return {"status": "executed_real_3", "count": counter[0]}

        res3 = enforcer.execute_command({"type": "transfer", "is_state_changing": True, "idempotency_key": "txn_123"}, execute_action)
        self.assertEqual(res3["status"], "executed_real_3")
        self.assertEqual(res3["count"], 1)

        # Valid: Duplicate state-changing with idempotency key (skipped)
        res4 = enforcer.execute_command({"type": "transfer", "is_state_changing": True, "idempotency_key": "txn_123"}, execute_action)
        self.assertEqual(res4["status"], "executed_real_3")
        self.assertEqual(res4["count"], 1) # count did not increase
        self.assertTrue(res4["_idempotent_replay"])

        # Invalid: State-changing, not idempotent by design, no key
        with self.assertRaises(StatefulIdempotencyError) as ctx:
            enforcer.execute_command({"type": "transfer", "is_state_changing": True}, execute_action)
        self.assertIn("Every state-changing command MUST be idempotent or carry an idempotency key", str(ctx.exception))

    def test_capacity_lease_manager(self):
        manager = StatefulCapacityLeaseManager(self.db, total_capacity=100)

        # Test Lease creation
        self.assertTrue(manager.lease_capacity("lease_1", amount=40))
        self.assertEqual(manager.get_available_capacity(), 60)

        # Test valid dispatch with lease
        self.assertTrue(manager.dispatch_job("job_1", required_capacity=30, lease_id="lease_1"))

        # Test invalid dispatch without lease
        with self.assertRaises(StatefulCapacityLeaseError) as ctx:
            manager.dispatch_job("job_2", required_capacity=10, lease_id=None)
        self.assertIn("Capacity MUST be leased/reserved before job dispatch", str(ctx.exception))

        # Test invalid dispatch with invalid lease
        with self.assertRaises(StatefulCapacityLeaseError):
             manager.dispatch_job("job_2", required_capacity=10, lease_id="invalid_lease")

        # Test invalid dispatch with insufficient leased capacity
        with self.assertRaises(StatefulCapacityLeaseError) as ctx:
            manager.dispatch_job("job_2", required_capacity=50, lease_id="lease_1")
        self.assertIn("insufficient capacity", str(ctx.exception))

        # Test lease expiration automatically releases capacity
        # We manually hack the expires_at for testing
        self.db.execute("UPDATE part7_capacity_leases SET expires_at=? WHERE lease_id=?", (time.time() - 10, "lease_1"))
        self.assertEqual(manager.get_available_capacity(), 100) # Should automatically expire

if __name__ == "__main__":
    unittest.main()
