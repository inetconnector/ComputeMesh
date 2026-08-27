"""Regression tests for privacy-by-design browser resource restrictions."""

import unittest

from services.gateway.security import SECURITY_HEADERS


class PrivacyCspTests(unittest.TestCase):
    def test_csp_is_first_party_only(self) -> None:
        csp = SECURITY_HEADERS["Content-Security-Policy"]
        self.assertIn("default-src 'self'", csp)
        self.assertIn("font-src 'self'", csp)
        self.assertIn("connect-src 'self'", csp)
        self.assertIn("object-src 'none'", csp)
        self.assertNotIn("fonts.googleapis.com", csp)
        self.assertNotIn("fonts.gstatic.com", csp)
        self.assertNotIn("cdn.jsdelivr.net", csp)
        self.assertNotIn("https:", csp)


if __name__ == "__main__":
    unittest.main()
