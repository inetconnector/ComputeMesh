from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from tools.stripe_preflight import evaluate_environment, fetch_health


class TestStripePreflight(unittest.TestCase):
    def test_environment_check_does_not_require_secret_values_in_result(self) -> None:
        with tempfile.TemporaryDirectory() as tempdir:
            checks = evaluate_environment({
                "STRIPE_API_KEY": "sk_live_private-value",
                "STRIPE_WEBHOOK_SECRET": "whsec_private-value",
                "COMPUTEMESH_STRIPE_SESSION_STORE": str(Path(tempdir) / "sessions.json"),
            })
        self.assertTrue(checks["configuration_ready"])
        self.assertNotIn("private", repr(checks))

    def test_health_check_accepts_only_ready_gateway_contract(self) -> None:
        class Response:
            status = 200

            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return False

            def read(self):
                return b'{"status":"healthy","stripe":{"status":"ready","mode":"live","checkout_configured":true,"webhook_configured":true,"session_store_configured":true}}'

        with patch("tools.stripe_preflight.urllib.request.urlopen", return_value=Response()):
            result = fetch_health("https://example.test")
        self.assertTrue(result["healthy"])
        self.assertEqual(result["stripe"]["mode"], "live")


if __name__ == "__main__":
    unittest.main()
