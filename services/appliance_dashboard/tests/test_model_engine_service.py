"""Tests for Multi-GPU ModelEngineService."""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from services.appliance_dashboard.model_engine_service import (
    EngineState,
    ModelEngineConfig,
    ModelEngineService,
)


class TestModelEngineService(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.dummy_model = Path(self.temp_dir.name) / "test_model.gguf"
        self.dummy_model.write_bytes(b"GGUF" + b"_TEST_HEADER_DATA_1234567890")

        self.mock_config = ModelEngineConfig(
            host="127.0.0.1",
            port=18081,
            executable_path="nonexistent-mock-llama-server",
            startup_max_wait_seconds=1.0,
            smoketest_timeout_seconds=1.0,
            drain_timeout_seconds=0.5,
            allow_mock=True,
        )
        self.prod_config = ModelEngineConfig(
            host="127.0.0.1",
            port=18081,
            executable_path="nonexistent-prod-llama-server",
            startup_max_wait_seconds=1.0,
            smoketest_timeout_seconds=1.0,
            drain_timeout_seconds=0.5,
            allow_mock=False,
        )
        self.service = ModelEngineService(self.mock_config)

    def tearDown(self) -> None:
        self.service.stop_model(drain_timeout=0.2)
        self.temp_dir.cleanup()

    def test_production_mode_fails_without_binary(self) -> None:
        prod_svc = ModelEngineService(self.prod_config)
        ok = prod_svc.start_model(
            model_path=str(self.dummy_model),
            model_id="qwen2.5-32b-instruct",
        )
        self.assertFalse(ok)
        self.assertEqual(prod_svc.state, EngineState.ERROR)
        self.assertIn("not found in system PATH", prod_svc.last_error or "")

    def test_compute_model_digest(self) -> None:
        digest = self.service.compute_model_digest(self.dummy_model)
        self.assertTrue(digest.startswith("sha256:"))
        self.assertEqual(len(digest), 71)

    def test_kv_cache_calculation(self) -> None:
        # Context 8192, 32 layers, 32 heads, 128 d_head, 2 bytes/elem
        kv_bytes = self.service.compute_kv_cache_bytes(context_size=8192, n_layers=32, n_heads=32, d_head=128)
        expected = 2 * 32 * 32 * 128 * 8192 * 2
        self.assertEqual(kv_bytes, expected)
        self.assertGreater(kv_bytes, 1024 * 1024 * 500)  # > 500MB

    def test_start_and_stop_lifecycle_mock_mode(self) -> None:
        # Starting with dummy model file
        ok = self.service.start_model(
            model_path=str(self.dummy_model),
            model_id="qwen2.5-32b-instruct",
            context_size=8192,
            total_layers=64,
        )
        self.assertTrue(ok)
        self.assertEqual(self.service.state, EngineState.READY)
        self.assertEqual(self.service.active_model_id, "qwen2.5-32b-instruct")

        status = self.service.get_status()
        self.assertEqual(status["state"], "READY")
        self.assertEqual(status["active_model_id"], "qwen2.5-32b-instruct")
        self.assertTrue(status["active_model_digest"].startswith("sha256:"))

        # Stream lease acquisition and release
        self.assertTrue(self.service.acquire_stream())
        self.assertEqual(self.service.active_streams, 1)
        self.service.release_stream()
        self.assertEqual(self.service.active_streams, 0)

        # Graceful stop
        self.service.stop_model(drain_timeout=0.2)
        self.assertEqual(self.service.state, EngineState.STOPPED)
        self.assertIsNone(self.service.active_model_id)

    def test_start_nonexistent_model_returns_error(self) -> None:
        ok = self.service.start_model(
            model_path="/path/does/not/exist/model.gguf",
            model_id="missing-model",
        )
        self.assertFalse(ok)
        self.assertEqual(self.service.state, EngineState.ERROR)
        self.assertIn("not found", self.service.last_error or "")


if __name__ == "__main__":
    unittest.main()
