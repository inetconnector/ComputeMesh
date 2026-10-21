"""Tests for ComputeMesh Architecture Hardening & Fault Tolerance Engine (Part 4)."""

import unittest
from services.orchestrator.architecture_hardening_part4 import (
    SplitPhasePerformanceModel,
    SplitPhaseModelingError
)

class TestArchitectureHardeningPart4(unittest.TestCase):
    """Exhaustive tests for Part 4 invariants ensuring 100% real implementation (Rule 7)."""

    def setUp(self):
        self.performance_model = SplitPhasePerformanceModel()

    def test_split_phase_performance_model_success(self):
        """Test that prefill and decode phases are modeled separately and correctly."""
        node_profile = {
            "prefill_speed_tps": 100.0,
            "decode_speed_tps": 20.0
        }

        # 500 prompt tokens / 100 tps = 5.0 sec prefill
        # 100 decode tokens / 20 tps = 5.0 sec decode
        result = self.performance_model.estimate_job_performance(
            node_profile=node_profile,
            prompt_tokens=500,
            expected_decode_tokens=100
        )

        self.assertEqual(result["estimated_prefill_time_sec"], 5.0)
        self.assertEqual(result["estimated_decode_time_sec"], 5.0)
        self.assertEqual(result["total_estimated_time_sec"], 10.0)

        # 1000 prompt tokens / 100 tps = 10.0 sec prefill
        # 100 decode tokens / 20 tps = 5.0 sec decode
        result2 = self.performance_model.estimate_job_performance(
            node_profile=node_profile,
            prompt_tokens=1000,
            expected_decode_tokens=100
        )
        self.assertEqual(result2["estimated_prefill_time_sec"], 10.0)
        self.assertEqual(result2["estimated_decode_time_sec"], 5.0)
        self.assertEqual(result2["bottleneck"], "prefill")

    def test_split_phase_performance_model_missing_metrics(self):
        """Test that the model enforces both prefill and decode metrics to be present."""
        node_profile_missing_decode = {
            "prefill_speed_tps": 100.0
        }

        with self.assertRaises(SplitPhaseModelingError) as ctx:
            self.performance_model.estimate_job_performance(
                node_profile=node_profile_missing_decode,
                prompt_tokens=500,
                expected_decode_tokens=100
            )
        self.assertIn("MUST provide separate", str(ctx.exception))

    def test_split_phase_performance_model_invalid_tokens(self):
        """Test that the model enforces non-negative token counts."""
        node_profile = {
            "prefill_speed_tps": 100.0,
            "decode_speed_tps": 20.0
        }

        with self.assertRaises(SplitPhaseModelingError) as ctx:
            self.performance_model.estimate_job_performance(
                node_profile=node_profile,
                prompt_tokens=-10,
                expected_decode_tokens=100
            )
        self.assertIn("must be non-negative", str(ctx.exception))

    def test_split_phase_performance_model_zero_tps(self):
        """Test that the model handles zero or negative TPS by rejecting it to avoid division by zero."""
        node_profile = {
            "prefill_speed_tps": 0.0,
            "decode_speed_tps": 20.0
        }

        with self.assertRaises(SplitPhaseModelingError) as ctx:
            self.performance_model.estimate_job_performance(
                node_profile=node_profile,
                prompt_tokens=500,
                expected_decode_tokens=100
            )
        self.assertIn("strictly positive", str(ctx.exception))

if __name__ == '__main__':
    unittest.main()
