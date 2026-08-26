"""Unit tests for ComputeMesh Central Configuration System."""
import os
from pathlib import Path
import sys
import unittest

REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from services.common.config import (
    CONFIG,
    ComputeMeshConfig,
    EndpointConfig,
    PortConfig,
    TeaserConfig,
)


class TestConfig(unittest.TestCase):
    def test_default_config_singleton(self) -> None:
        self.assertIsInstance(CONFIG, ComputeMeshConfig)
        self.assertIsInstance(CONFIG.ports, PortConfig)
        self.assertIsInstance(CONFIG.endpoints, EndpointConfig)
        self.assertIsInstance(CONFIG.teaser, TeaserConfig)

        self.assertEqual(CONFIG.ports.gateway, 8000)
        self.assertEqual(CONFIG.ports.portal, 3000)
        self.assertEqual(CONFIG.ports.appliance_dashboard, 8080)
        self.assertEqual(CONFIG.teaser.max_free_requests, 20)
        self.assertEqual(CONFIG.teaser.max_free_tokens, 8192)
        self.assertEqual(CONFIG.teaser.window_seconds, 14400)

    def test_custom_domain_override(self) -> None:
        cfg = EndpointConfig(domain="custom.mesh.internal")
        self.assertEqual(cfg.domain, "custom.mesh.internal")
        self.assertEqual(cfg.base_url, "https://custom.mesh.internal")
        self.assertEqual(cfg.api_url, "https://custom.mesh.internal/v1")

    def test_teaser_config_parameters(self) -> None:
        teaser = TeaserConfig(max_free_requests=50, max_free_tokens=16384, window_seconds=7200, enabled=True)
        self.assertEqual(teaser.max_free_requests, 50)
        self.assertEqual(teaser.max_free_tokens, 16384)
        self.assertEqual(teaser.window_seconds, 7200)
        self.assertTrue(teaser.enabled)


if __name__ == "__main__":
    unittest.main()
