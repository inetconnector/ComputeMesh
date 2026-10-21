"""Tests for ComputeMesh Architecture Hardening & Fault Tolerance Engine (Part 6)."""
from __future__ import annotations

import unittest

from services.scheduler.architecture_hardening_part6 import (
    ExecutionPathOptimizer,
    OSNeutralProtocolEnforcer,
    ComponentBoundaryEnforcer,
    WholeExecutionPathError,
    OSNeutralContractError,
    ExplicitBoundaryError,
)

class TestArchitectureHardeningPart6(unittest.TestCase):
    def test_whole_execution_path(self):
        optimizer = ExecutionPathOptimizer()

        # Valid: single node plan
        plan1 = {"provider_node_ids": ["node1"]}
        optimizer.optimize_and_verify(plan1)
        self.assertTrue(plan1.get("execution_path_optimized"))

        # Valid: multi node plan with whole path metrics
        plan2 = {"provider_node_ids": ["node1", "node2"], "network_latency_ms": 15, "tensor_split": [0.5, 0.5]}
        optimizer.optimize_and_verify(plan2)
        self.assertTrue(plan2.get("execution_path_optimized"))
        self.assertEqual(plan2.get("path_optimization_applied"), "balanced_compute")

        # Valid: multi node plan with high latency (heuristic optimization applies)
        plan3 = {"provider_node_ids": ["node1", "node2"], "network_latency_ms": 100, "tensor_split": [0.5, 0.5]}
        optimizer.optimize_and_verify(plan3)
        self.assertTrue(plan3.get("execution_path_optimized"))
        self.assertEqual(plan3.get("path_optimization_applied"), "latency_heuristic")
        self.assertEqual(plan3.get("tensor_split"), [0.6, 0.4])

        # Valid: single element tensor split handles length safely
        plan4 = {"provider_node_ids": ["node1", "node2"], "network_latency_ms": 100, "tensor_split": [1.0]}
        optimizer.optimize_and_verify(plan4)
        self.assertTrue(plan4.get("execution_path_optimized"))
        self.assertEqual(plan4.get("path_optimization_applied"), "balanced_compute")

        # Invalid: multi node plan missing path metrics
        invalid_plan1 = {"provider_node_ids": ["node1", "node2"]}
        with self.assertRaises(WholeExecutionPathError) as ctx:
            optimizer.optimize_and_verify(invalid_plan1)
        self.assertIn("MUST optimize the whole execution path", str(ctx.exception))

        # Invalid: explicitly targets individual GPU
        invalid_plan2 = {"optimization_target": "individual_gpu"}
        with self.assertRaises(WholeExecutionPathError) as ctx:
            optimizer.optimize_and_verify(invalid_plan2)
        self.assertIn("MUST optimize the whole execution path", str(ctx.exception))

    def test_os_neutral_contract(self):
        enforcer = OSNeutralProtocolEnforcer()

        # Valid: OS-neutral contract
        contract = {"ram_gb": 16, "model_id": "llama-3", "nested": {"param": 1}, "list_field": [{"valid": 1}]}
        enforcer.validate_contract(contract)

        # Invalid: OS-specific key in list
        with self.assertRaises(OSNeutralContractError):
            enforcer.validate_contract({"items": ["windows_registry"]})

        # Invalid: OS-specific path string in list
        with self.assertRaises(OSNeutralContractError):
            enforcer.validate_contract({"items": ["C:\\Windows\\System32"]})

        # Invalid: OS-specific contract at root
        invalid_contract1 = {"windows_registry": "HKLM\\Software\\ComputeMesh"}
        with self.assertRaises(OSNeutralContractError) as ctx:
            enforcer.validate_contract(invalid_contract1)
        self.assertIn("Protocol contracts MUST remain OS-neutral", str(ctx.exception))

        # Invalid: OS-specific contract nested
        invalid_contract2 = {"valid": "data", "nested": {"linux_cgroups": "/sys/fs/cgroup"}}
        with self.assertRaises(OSNeutralContractError) as ctx:
            enforcer.validate_contract(invalid_contract2)
        self.assertIn("Protocol contracts MUST remain OS-neutral", str(ctx.exception))

    def test_explicit_boundary(self):
        enforcer = ComponentBoundaryEnforcer()

        # Valid: explicit boundaries
        payload = {"data": "test"}
        result = enforcer.call_across_boundary("scheduler", "dispatcher", payload)
        self.assertTrue(result["boundary_transition"]["explicit"])
        self.assertEqual(result["boundary_transition"]["source"], "scheduler")
        self.assertEqual(result["boundary_transition"]["target"], "dispatcher")

        # Invalid: implicit/unknown boundaries
        with self.assertRaises(ExplicitBoundaryError) as ctx:
            enforcer.call_across_boundary("scheduler", "unknown_component", {})
        self.assertIn("The boundary MUST remain explicit in code", str(ctx.exception))

if __name__ == "__main__":
    unittest.main()
