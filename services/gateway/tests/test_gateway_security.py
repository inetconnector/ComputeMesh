"""Unit tests for ComputeMesh Hardened Security, Rate Limiting & Data Sanitization."""
from pathlib import Path
import sys
import time
import unittest

REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from services.gateway.security import (
    MAX_REQUEST_PAYLOAD_BYTES,
    RateLimiter,
    SECURITY_HEADERS,
    sanitize_error_message,
    zero_memory_bytes,
)
from services.portal.server import _safe_resolve_portal_file


class TestGatewaySecurity(unittest.TestCase):
    def test_security_headers_completeness(self) -> None:
        self.assertIn("X-Content-Type-Options", SECURITY_HEADERS)
        self.assertEqual(SECURITY_HEADERS["X-Content-Type-Options"], "nosniff")
        self.assertIn("X-Frame-Options", SECURITY_HEADERS)
        self.assertEqual(SECURITY_HEADERS["X-Frame-Options"], "DENY")
        self.assertIn("Strict-Transport-Security", SECURITY_HEADERS)
        self.assertIn("max-age=63072000", SECURITY_HEADERS["Strict-Transport-Security"])
        self.assertIn("Content-Security-Policy", SECURITY_HEADERS)
        self.assertIn("Server", SECURITY_HEADERS)
        self.assertFalse("BaseHTTP" in SECURITY_HEADERS["Server"])

    def test_rate_limiter_allows_burst_then_limits(self) -> None:
        limiter = RateLimiter(default_rate_per_min=60.0, authenticated_rate_per_min=600.0)
        client_id = "test_ip_192_0_2_1"

        # Default allows burst of 5 tokens
        for _ in range(5):
            allowed, retry = limiter.is_allowed(client_id, is_authenticated=False)
            self.assertTrue(allowed)
            self.assertEqual(retry, 0.0)

        # 6th request immediately exceeds burst capacity
        allowed, retry = limiter.is_allowed(client_id, is_authenticated=False)
        self.assertFalse(allowed)
        self.assertGreater(retry, 0.0)

    def test_sanitize_error_message(self) -> None:
        raw_error = "Error in /root/ComputeMesh/services/gateway/server.py with key cm_live_1234567890abcdef12345678"
        sanitized = sanitize_error_message(raw_error)
        self.assertNotIn("/root/ComputeMesh", sanitized)
        self.assertNotIn("cm_live_1234567890abcdef12345678", sanitized)
        self.assertIn("[internal_path]", sanitized)
        self.assertIn("[REDACTED_SECRET]", sanitized)

    def test_zero_memory_bytes(self) -> None:
        sensitive_buf = bytearray(b"super_secret_ai_prompt_data_12345")
        self.assertGreater(sum(sensitive_buf), 0)
        zero_memory_bytes(sensitive_buf)
        self.assertEqual(sum(sensitive_buf), 0)
        self.assertEqual(sensitive_buf, bytearray(len(sensitive_buf)))

    def test_path_traversal_immunity(self) -> None:
        # Valid files
        self.assertIsNotNone(_safe_resolve_portal_file("index.html"))
        self.assertIsNotNone(_safe_resolve_portal_file("portal.css"))

        # Malicious traversal attempts
        self.assertIsNone(_safe_resolve_portal_file("../../etc/passwd"))
        self.assertIsNone(_safe_resolve_portal_file("/etc/shadow"))
        self.assertIsNone(_safe_resolve_portal_file("..\\..\\windows\\system32\\cmd.exe"))
        self.assertIsNone(_safe_resolve_portal_file("index.html\0.exe"))


if __name__ == "__main__":
    unittest.main()
