"""Tests for Architecture Hardening Part 2."""
import unittest
import time
from services.orchestrator.architecture_hardening_part2 import (
    NodeLifecycleManager,
    NodeDrainingError,
    StrictStateRecovery,
    StateRecoveryError,
    PrivacyConstraintEvaluator,
    PrivacyConstraintError,
    ContentAddressedArtifactRegistry,
    ImmutableArtifactError,
    PrivacyPreservingTelemetry
)

class TestNodeLifecycleManager(unittest.TestCase):
    def test_node_lifecycle_manager_draining(self):
        manager = NodeLifecycleManager()
        self.assertEqual(manager.get_state(), "ACTIVE")

        manager.admit_job()
        manager.admit_job()

        manager.start_drain()
        self.assertTrue(manager.is_draining())
        self.assertEqual(manager.get_state(), "DRAINING")

        with self.assertRaises(NodeDrainingError):
            manager.admit_job()

        manager.complete_job()
        self.assertEqual(manager.get_state(), "DRAINING")

        manager.complete_job()
        self.assertEqual(manager.get_state(), "OFFLINE")

class TestStrictStateRecovery(unittest.TestCase):
    def test_strict_state_recovery(self):
        recovery = StrictStateRecovery()
        state_id = "job_123"
        valid_data = b"state_data_v1"
        corrupted_data = b"state_data_v1_corrupted"

        recovery.save_checkpoint(state_id, valid_data)

        # Should succeed
        self.assertTrue(recovery.recover_state(state_id, valid_data))

        # Should fail on corrupted data
        with self.assertRaises(StateRecoveryError):
            recovery.recover_state(state_id, corrupted_data)

        # Should fail on unknown state
        with self.assertRaises(StateRecoveryError):
            recovery.recover_state("unknown_job", valid_data)

class TestPrivacyConstraintEvaluator(unittest.TestCase):
    def test_privacy_constraint_evaluator(self):
        evaluator = PrivacyConstraintEvaluator()
        provider_caps = ["HIPAA_COMPLIANT", "EU_REGION"]

        # Should succeed
        self.assertTrue(evaluator.evaluate_placement(provider_caps, ["HIPAA_COMPLIANT"]))

        # Should fail
        with self.assertRaises(PrivacyConstraintError):
            evaluator.evaluate_placement(provider_caps, ["SOC2_COMPLIANT"])

class TestContentAddressedArtifactRegistry(unittest.TestCase):
    def test_content_addressed_artifact_registry(self):
        registry = ContentAddressedArtifactRegistry()
        data = b"model_weights_123"

        hash_key = registry.register_artifact(data)

        self.assertEqual(registry.get_artifact(hash_key), data)
        self.assertTrue(registry.verify_artifact(hash_key, data))

        with self.assertRaises(ImmutableArtifactError):
            registry.verify_artifact(hash_key, b"different_data")

        with self.assertRaises(ImmutableArtifactError):
            registry.get_artifact("unknown_hash")

class TestPrivacyPreservingTelemetry(unittest.TestCase):
    def test_privacy_preserving_telemetry(self):
        telemetry = PrivacyPreservingTelemetry()

        telemetry.record_event(
            event_type="generation",
            duration_ms=150.5,
            metadata={"model": "llama3", "prompt": "secret user prompt", "output": "secret model output"},
            raw_prompt="secret user prompt",
            raw_output="secret model output"
        )

        logs = telemetry.get_logs()
        self.assertEqual(len(logs), 1)

        event = logs[0]
        self.assertEqual(event["type"], "generation")
        self.assertEqual(event["duration_ms"], 150.5)
        self.assertNotIn("prompt", event["metadata"])
        self.assertNotIn("output", event["metadata"])
        self.assertEqual(event["metadata"]["model"], "llama3")

if __name__ == "__main__":
    unittest.main()
