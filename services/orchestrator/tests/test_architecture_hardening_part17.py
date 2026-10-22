"""Unit tests for Architecture Hardening (Part 17)."""

import sqlite3
import time
import unittest

from services.orchestrator.architecture_hardening_part17 import (
    PlacementRevisionEnforcer,
    RateBudgetLimitEnforcer,
    NodeWorkloadBoundaryEnforcer,
    PlacementRevisionError,
    RateBudgetLimitError,
    WorkloadBoundaryError
)

class TestPlacementRevisionEnforcer(unittest.TestCase):
    def setUp(self):
        self.db = sqlite3.connect(":memory:")
        self.enforcer = PlacementRevisionEnforcer(self.db)

    def tearDown(self):
        self.db.close()

    def test_create_placement(self):
        self.enforcer.create_placement("place_1")

        row = self.db.execute("SELECT revision FROM placement_revisions WHERE placement_id = 'place_1'").fetchone()
        self.assertIsNotNone(row)
        self.assertEqual(row[0], 1)

    def test_create_duplicate_placement_raises_error(self):
        self.enforcer.create_placement("place_1")
        with self.assertRaises(PlacementRevisionError):
            self.enforcer.create_placement("place_1")

    def test_update_placement_success(self):
        self.enforcer.create_placement("place_1")
        new_rev = self.enforcer.update_placement("place_1", 1)
        self.assertEqual(new_rev, 2)

        row = self.db.execute("SELECT revision FROM placement_revisions WHERE placement_id = 'place_1'").fetchone()
        self.assertEqual(row[0], 2)

    def test_update_nonexistent_placement_raises_error(self):
        with self.assertRaises(PlacementRevisionError):
            self.enforcer.update_placement("place_missing", 1)

    def test_update_placement_revision_mismatch_raises_error(self):
        self.enforcer.create_placement("place_1")
        with self.assertRaises(PlacementRevisionError):
            self.enforcer.update_placement("place_1", 2)  # Expected 1

class TestRateBudgetLimitEnforcer(unittest.TestCase):
    def setUp(self):
        self.db = sqlite3.connect(":memory:")
        self.enforcer = RateBudgetLimitEnforcer(self.db)

    def tearDown(self):
        self.db.close()

    def test_set_limit_and_consume(self):
        self.enforcer.set_limit("user_1", 100)
        self.enforcer.consume_budget("user_1", 50, current_time=1.0)

        row = self.db.execute("SELECT budget_spent FROM budget_limits WHERE user_id = 'user_1'").fetchone()
        self.assertEqual(row[0], 50)

    def test_consume_exceeds_budget(self):
        self.enforcer.set_limit("user_1", 100)
        with self.assertRaises(RateBudgetLimitError):
            self.enforcer.consume_budget("user_1", 101, current_time=1.0)

    def test_consume_rate_limit(self):
        self.enforcer.set_limit("user_1", 100)
        self.enforcer.consume_budget("user_1", 10, current_time=1.0)
        with self.assertRaises(RateBudgetLimitError):
            self.enforcer.consume_budget("user_1", 10, current_time=1.05)  # Default min_interval is 0.1

    def test_consume_no_limit_set(self):
        with self.assertRaises(RateBudgetLimitError):
            self.enforcer.consume_budget("user_missing", 10, current_time=1.0)

class TestNodeWorkloadBoundaryEnforcer(unittest.TestCase):
    def setUp(self):
        self.db = sqlite3.connect(":memory:")
        self.enforcer = NodeWorkloadBoundaryEnforcer(self.db)

    def tearDown(self):
        self.db.close()

    def test_set_and_validate_workload(self):
        self.enforcer.set_boundary("node_1", ["model_a", "model_b"], 1024)
        # Should succeed
        self.enforcer.validate_workload("node_1", "model_a", 512)

    def test_validate_unallowed_model(self):
        self.enforcer.set_boundary("node_1", ["model_a"], 1024)
        with self.assertRaises(WorkloadBoundaryError):
            self.enforcer.validate_workload("node_1", "model_b", 512)

    def test_validate_exceeds_memory(self):
        self.enforcer.set_boundary("node_1", ["model_a"], 1024)
        with self.assertRaises(WorkloadBoundaryError):
            self.enforcer.validate_workload("node_1", "model_a", 2048)

    def test_validate_no_boundary_set(self):
        with self.assertRaises(WorkloadBoundaryError):
            self.enforcer.validate_workload("node_missing", "model_a", 512)

if __name__ == '__main__':
    unittest.main()
