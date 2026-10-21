"""Tests for ComputeMesh Architecture Hardening & Fault Tolerance Engine (Part 5)."""

import unittest
import time
from services.orchestrator.architecture_hardening_part5 import (
    AutomaticCapacityRelease,
    AgentExecutionPolicy,
    RelayPolicyEnforcer,
    CryptographicProofClaimVerifier,
    MoEWANCostMeasurer,
    AgentExecutionPolicyError,
    RelayPolicyError,
    CryptographicProofError,
    MoEWANCostError
)

class TestArchitectureHardeningPart5(unittest.TestCase):
    """Exhaustive tests for Part 5 invariants ensuring 100% real implementation (Rule 7)."""

    def test_automatic_capacity_release(self):
        """Test that expired leases release capacity automatically."""
        manager = AutomaticCapacityRelease()
        self.assertEqual(manager.check_capacity(), 100)

        # Lease for 0.1 seconds
        self.assertTrue(manager.lease_capacity("lease1", 0.1))
        self.assertEqual(manager.check_capacity(), 99)

        # Wait for expiry
        time.sleep(0.2)

        # Check capacity is released automatically on next check
        self.assertEqual(manager.check_capacity(), 100)

    def test_agent_execution_policy_allowed(self):
        """Test allowed execution commands."""
        policy = AgentExecutionPolicy()
        result = policy.execute_command("predict", {"input": "test"})
        self.assertEqual(result["status"], "ok")

    def test_agent_execution_policy_forbidden(self):
        """Test that the agent MUST NOT expose a generic remote-execution API."""
        policy = AgentExecutionPolicy()
        with self.assertRaises(AgentExecutionPolicyError) as ctx:
            policy.execute_command("bash", {"cmd": "ls"})
        self.assertIn("MUST NOT expose a generic remote-execution API", str(ctx.exception))

    def test_relay_policy_enforcer_success(self):
        """Test relay forwards when policies are strictly met."""
        enforcer = RelayPolicyEnforcer()
        config = {"mTLS": True, "E2E_Encryption": True, "Strict_Auth": True}
        result = enforcer.forward_request(config, {"data": "test"})
        self.assertTrue(result["forwarded"])

    def test_relay_policy_enforcer_weakened(self):
        """Test that relays MUST NOT silently weaken end-to-end policy."""
        enforcer = RelayPolicyEnforcer()
        config = {"mTLS": True, "E2E_Encryption": False, "Strict_Auth": True}
        with self.assertRaises(RelayPolicyError) as ctx:
            enforcer.forward_request(config, {"data": "test"})
        self.assertIn("MUST NOT silently weaken end-to-end policy", str(ctx.exception))

    def test_cryptographic_proof_claim_valid(self):
        """Test valid cryptographic proof claim."""
        verifier = CryptographicProofClaimVerifier()
        import hashlib
        expected_hash = hashlib.sha256("test_output".encode("utf-8")).hexdigest()
        result = {"output": "test_output", "cryptographic_proof": expected_hash}
        self.assertTrue(verifier.verify_inference_result(result, "zk-SNARK-v1"))

    def test_cryptographic_proof_claim_no_mechanism(self):
        """Test claim without mechanism is rejected."""
        verifier = CryptographicProofClaimVerifier()
        import hashlib
        expected_hash = hashlib.sha256("test_output".encode("utf-8")).hexdigest()
        result = {"output": "test_output", "cryptographic_proof": expected_hash}
        with self.assertRaises(CryptographicProofError) as ctx:
            verifier.verify_inference_result(result, None)
        self.assertIn("MUST NOT claim cryptographic proof without specifying", str(ctx.exception))

    def test_cryptographic_proof_claim_unverified_mechanism(self):
        """Test claim with unverified mechanism is rejected."""
        verifier = CryptographicProofClaimVerifier()
        import hashlib
        expected_hash = hashlib.sha256("test_output".encode("utf-8")).hexdigest()
        result = {"output": "test_output", "cryptographic_proof": expected_hash}
        with self.assertRaises(CryptographicProofError) as ctx:
            verifier.verify_inference_result(result, "untested-crypto-v2")
        self.assertIn("is not independently evaluated", str(ctx.exception))

    def test_moe_wan_cost_measurement(self):
        """Test that MoE WAN costs MUST be measured."""
        measurer = MoEWANCostMeasurer()

        # Evaluating before measuring is rejected
        with self.assertRaises(MoEWANCostError) as ctx:
            measurer.evaluate_placement()
        self.assertIn("MUST measure MoE routing effects", str(ctx.exception))

        # Record measurements
        measurer.record_routing_cost(10.5, 50.0, 0.2)
        measurer.record_routing_cost(12.0, 55.0, 0.3)

        eval_result = measurer.evaluate_placement()
        self.assertEqual(eval_result["measurements_count"], 2)
        self.assertEqual(eval_result["average_activation_traffic_mb"], 11.25)
        self.assertEqual(eval_result["average_tail_latency_ms"], 52.5)

if __name__ == '__main__':
    unittest.main()
